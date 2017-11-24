import gym
import sys
from collections import OrderedDict
from surreal.agent.base import AgentMode
from surreal.agent.q_agent import QAgent
from surreal.env import *
from surreal.session import *
from surreal.main.cartpole_configs import *

agent_id = 0
agent_mode = AgentMode.eval_deterministic

env = GymAdapter(gym.make('CartPole-v0'))
env = TensorplexMonitor(
    env,
    agent_id=agent_id,
    agent_mode=agent_mode,
    session_config=cartpole_session_config,
    separate_plots=False,
)

q_agent = QAgent(
    learn_config=cartpole_learn_config,
    env_config=cartpole_env_config,
    session_config=cartpole_session_config,
    agent_id=agent_id,
    agent_mode=agent_mode,
)


q_agent.pull_parameters()
obs, info = env.reset()
while True:
    action = q_agent.act(U.to_float_tensor(obs))
    obs, reward, done, info = env.step(action)
    if done:
        q_agent.pull_parameters()
        obs, info = env.reset()
        # print(q_agent.pull_parameter_info())
    #     eps_rewards = env.get_episode_rewards()
    #     num_eps = len(env.get_episode_rewards())
    #     tensorplex.add_scalar(':reward', eps_rewards[-1], num_eps)
    #     avg_speed = 1 / (float(np.mean(env.get_episode_duration()[-10:])) + 1e-6)
    #     tensorplex.add_scalar(':iter_per_s', avg_speed, num_eps)
    #
    #     if info_print.track_increment():
    #         # book-keeping, TODO should be done in Evaluator
    #         info_table = []
    #         avg_reward = np.mean(env.get_episode_rewards()[-10:])
    #         info_table.append(['Last 10 rewards', U.fformat(avg_reward, 3)])
    #         info_table.append(['Exploration',
    #                        str(int(100 * q_agent.exploration.value(T)))+'%'])
    #         avg_speed = 1 / (float(np.mean(env.get_episode_duration()[-10:])) + 1e-6)
    #         info_table.append(['Speed iter/s', U.fformat(avg_speed, 1)])
    #         info_table.append(['Total steps', env.get_total_steps()])
    #         info_table.append(['Episodes', len(env.get_episode_rewards())])
    #         print(tabulate(info_table, tablefmt='fancy_grid'))