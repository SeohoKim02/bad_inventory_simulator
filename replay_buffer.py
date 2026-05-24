"""
replay_buffer.py — DQN 경험 재플레이 버퍼
────────────────────────────────────────────
기존 코드와 독립적으로 동작.
PyTorch / numpy 모두 호환.
"""
import numpy as np
from collections import deque
import random


class ReplayBuffer:
    """
    DQN Experience Replay Buffer.

    저장 구조: (state, action_id, reward, next_state, done)
    """

    def __init__(self, capacity: int = 10000):
        self.buffer   = deque(maxlen=capacity)
        self.capacity = capacity

    def push(self, state, action_id: int, reward: float, next_state, done: bool):
        self.buffer.append((
            np.array(state,      dtype=np.float32),
            int(action_id),
            float(reward),
            np.array(next_state, dtype=np.float32),
            bool(done),
        ))

    def sample(self, batch_size: int):
        batch = random.sample(self.buffer, min(batch_size, len(self.buffer)))
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.stack(states),
            np.array(actions,     dtype=np.int64),
            np.array(rewards,     dtype=np.float32),
            np.stack(next_states),
            np.array(dones,       dtype=np.float32),
        )

    def __len__(self):
        return len(self.buffer)

    @property
    def is_ready(self, min_size: int = 64) -> bool:
        return len(self.buffer) >= min_size
