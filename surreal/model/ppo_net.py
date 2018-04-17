import torch.nn as nn
from torch.autograd import Variable
from torch.nn.init import xavier_uniform
import surreal.utils as U
import torch.nn.functional as F
import numpy as np

from .model_builders import *
from .z_filter import ZFilter

class DiagGauss(object):
    '''
        Class that encapsulates Diagonal Gaussian Probability distribution
        Attributes:
            d: action dimension
        Member Functions:
            loglikelihood
            likelihood
            kl
            entropy
            sample
            maxprob
    '''
    def __init__(self, action_dim):
        self.d = action_dim

    def loglikelihood(self, a, prob):
        '''
            Method computes loglikelihood of action (a) given probability (prob)
        '''
        if len(a.size()) == 3:
            a = a.view(-1, self.d)
            prob = prob.view(-1, 2 * self.d)

        mean0 = prob[:, :self.d]
        std0 = prob[:, self.d:]
        return - 0.5 * (((a - mean0) / std0).pow(2)).sum(dim=1, keepdim=True) - 0.5 * np.log(
            2.0 * np.pi) * self.d - std0.log().sum(dim=1, keepdim=True)

    def likelihood(self, a, prob):
        '''
            Method computes likelihood of action (a) given probability (prob)
        '''
        return torch.clamp(self.loglikelihood(a, prob).exp(), min=1e-5)

    def kl(self, prob0, prob1):
        '''
            Method computes KL Divergence of between two probability distributions
            Note: this is D_KL(prob0 || prob1), not D_KL(prob1 || prob0)
        '''
        if len(prob0.size()) == 3:
            prob0 = prob0.view(-1, 2 * self.d)
            prob1 = prob1.view(-1, 2 * self.d)

        mean0 = prob0[:, :self.d]
        std0 = prob0[:, self.d:]
        mean1 = prob1[:, :self.d]
        std1 = prob1[:, self.d:]
        return ((std1 / std0).log()).sum(dim=1) + (
            (std0.pow(2) + (mean0 - mean1).pow(2)) / (2.0 * std1.pow(2))).sum(dim=1) - 0.5 * self.d

    def entropy(self, prob):
        '''
            Method computes entropy of a given probability (prob)
        '''
        if len(prob.size()) == 3:
            prob = prob.view(-1, 2 * self.d)

        std_nd = prob[:, self.d:]
        return 0.5 * std_nd.log().sum(dim=1) + .5 * np.log(2 * np.pi * np.e) * self.d

    def sample(self, prob):
        '''
            Method samples actions from probability distribution
        '''
        if len(prob.shape) == 3:
            prob_shape = prob.shape
            prob = prob.reshape(-1, self.d * 2)
        mean_nd = prob[:, :self.d]
        std_nd = prob[:, self.d:]
        return np.random.randn(prob.shape[0], self.d) * std_nd + mean_nd

    def maxprob(self, prob):
        '''
            Method deterministically sample actions of maximum likelihood
        '''
        if len(prob.shape) == 3:
            return prob[:, :, self.d]
        return prob[:, :self.d]


class PPOModel(U.Module):
    '''
        PPO Model class that wraps aroud the actor and critic networks
        Attributes:
            actor: Actor network, see surreal.model.model_builders.builders
            critic: Critic network, see surreal.model.model_builders.builders
            z_filter: observation z_filter. see surreal.model.z_filter
        Member functions:
            update_target_param: updates kept parameters to that of another model
            update_target_param: updates kept z_filter to that of another model
            forward_actor: forward pass actor to generate policy with option
                to use z-filter
            forward_actor: forward pass critic to generate policy with option
                to use z-filter
            z_update: updates Z_filter running obs mean and variance
    '''
    def __init__(self,
                 init_log_sig,
                 obs_dim,
                 action_dim,
                 use_z_filter,
                 rnn_config,
                 use_cuda):
        super(PPOModel, self).__init__()

        # hyperparameters
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.use_z_filter = use_z_filter
        self.init_log_sig = init_log_sig
        self.rnn_config = rnn_config

        self.rnn_stem = None
        if self.rnn_config.if_rnn_policy:
            self.rnn_stem = nn.LSTM(self.obs_dim,
                            self.rnn_config.rnn_hidden,
                            self.rnn_config.rnn_layer,
                            batch_first=True)
            if use_cuda:
                self.rnn_stem = self.rnn_stem.cuda()

        input_size = self.rnn_config.rnn_hidden if self.rnn_config.if_rnn_policy else self.obs_dim

        self.actor = PPO_ActorNetwork(input_size, 
                                      self.action_dim, 
                                      self.init_log_sig, 
                                      self.rnn_stem)
        self.critic = PPO_CriticNetwork(input_size, self.rnn_stem)
        if self.use_z_filter:
            self.z_filter = ZFilter(obs_dim, use_cuda=use_cuda)

    def update_target_params(self, net):
        '''
            updates kept parameters to that of another model
            Args:
                net: another PPO_Model instance
        '''
        self.actor.load_state_dict(net.actor.state_dict())
        self.critic.load_state_dict(net.critic.state_dict())
        if self.use_z_filter:
            self.z_filter.load_state_dict(net.z_filter.state_dict())

    def update_target_z_filter(self, net):
        '''
            updates kept z-filter to that of another model
            Args:
                net: another PPO_Model instance
        '''
        if self.use_z_filter:
            self.z_filter.load_state_dict(net.z_filter.state_dict())

    def forward_actor(self, obs, cells=None):
        '''
            forward pass actor to generate policy with option to use z-filter
            Args:
                obs -- batch of observations
            Returns:
                The output of actor network
        '''
        if self.use_z_filter:
            obs = self.z_filter.forward(obs)

        if self.rnn_config.if_rnn_policy:
            assert len(obs.size()) == 3
            obs, _ = self.rnn_stem(obs, cells) # assumes that input has the correct shape
            obs = obs.contiguous()
            output_shape = obs.size()
            obs = obs.view(-1, self.rnn_config.rnn_hidden)

        action = self.actor(obs)
        if self.rnn_config.if_rnn_policy:
            action = action.view(output_shape[0], output_shape[1], -1)
            
        return action

    def forward_critic(self, obs, cells=None):
        '''
            forward pass critic to generate policy with option to use z-filter
            Args: 
                obs -- batch of observations
            Returns:
                output of critic network
        '''
        if self.use_z_filter:
            obs = self.z_filter.forward(obs)

        if self.rnn_config.if_rnn_policy:
            obs, _ = self.rnn_stem(obs, cells)
            obs = obs.contiguous()
            output_shape = obs.size()
            obs = obs.view(-1, self.rnn_config.rnn_hidden)

        value = self.critic(obs)
        if self.rnn_config.if_rnn_policy:
            value = value.view(output_shape[0], output_shape[1], 1)

        return value

    def forward_actor_expose_cells(self, obs, cells=None):
        '''
            forward pass critic to generate policy with option to use z-filter
            also returns an updated LSTM hidden/cell state when necessary
            Args: 
                obs -- batch of observations
            Returns:
                output of critic network
        '''
        if self.use_z_filter:
            obs = self.z_filter.forward(obs)

        if self.rnn_config.if_rnn_policy:
            obs = obs.view(1, 1, -1) # assume input is shape (1, obs_dim)
            obs, cells = self.rnn_stem(obs, cells)
            
            # Note that this is effectively the same of a .detach() call.
            # .detach() is necessary here to prevent overflow of memory
            # otherwise rollout in length of thousands will prevent previously
            # accumulated hidden/cell states from being freed.
            cells = (Variable(cells[0].data),Variable(cells[1].data))
            obs = obs.contiguous()  
            obs = obs.view(-1, self.rnn_config.rnn_hidden)

        action = self.actor(obs) # shape (1, action_dim)

        return action, cells

    def z_update(self, obs):
        '''
            updates Z_filter running obs mean and variance
            Args: obs -- batch of observations
        '''
        if self.use_z_filter:
            self.z_filter.z_update(obs)
        else:
            raise ValueError('Z_update called when network is set to not use z_filter')