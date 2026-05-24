
"""
torch_dqn_agent.py — PyTorch 기반 DQN 에이전트
────────────────────────────────────────────────
기존 dqn_agent.py(numpy) 와 병렬 운영.
PyTorch 없으면 numpy fallback으로 자동 전환.

액션 공간 (7개):
  0 keep_inventory     — 현재 유지
  1 discount_sale      — 할인 판매
  2 one_plus_one       — 1+1 프로모션
  3 direct_transfer    — 직접 이동
  4 dc_transfer        — DC 경유 이동
  5 emergency_discount — 긴급 할인
  6 dispose            — 폐기

State vector (9개, 기존 STATE_COLUMNS 유지):
  state_source_stock, state_target_stock,
  state_source_sales_30d, state_target_sales_30d,
  state_inbound_days, state_unit_cost,
  state_distance_km, state_transfer_cost,
  state_promotion_net_cost
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

# ── PyTorch 가용성 체크 ──────────────────────────────────
try:
    import torch          # type: ignore[import]
    import torch.nn as nn # type: ignore[import]
    import torch.optim as optim # type: ignore[import]
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from replay_buffer import ReplayBuffer

# ── 액션 정의 (기존 rl_data_logger.ACTION_ID_MAP과 호환) ─
TORCH_ACTION_SPACE = [
    "keep_inventory",     # 0
    "discount_sale",      # 1
    "one_plus_one",       # 2
    "direct_transfer",    # 3
    "dc_transfer",        # 4
    "emergency_discount", # 5
    "dispose",            # 6
]
N_ACTIONS = len(TORCH_ACTION_SPACE)

# 기존 action_id 매핑과 교차 호환
LEGACY_TO_TORCH = {
    "keep":                 0,
    "discount_promotion":   1,
    "one_plus_one":         2,
    "direct_transfer":      3,
    "via_dc_transfer":      4,
    "multi_store_transfer": 3,
    "dispose":              6,
    "promotion":            1,
    "transfer":             3,
    "unknown":              0,
}

# ── State 컬럼 (기존 STATE_COLUMNS 일치) ─────────────────
STATE_COLS = [
    "state_source_stock",
    "state_target_stock",
    "state_source_sales_30d",
    "state_target_sales_30d",
    "state_inbound_days",
    "state_unit_cost",
    "state_distance_km",
    "state_transfer_cost",
    "state_promotion_net_cost",
]
N_STATES = len(STATE_COLS)


# ── Q-Network (PyTorch) ─────────────────────────────────
if TORCH_AVAILABLE:
    class QNetwork(nn.Module):
        def __init__(self, n_states: int, n_actions: int, hidden: int = 64):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(n_states, hidden),
                nn.ReLU(),
                nn.Linear(hidden, hidden),
                nn.ReLU(),
                nn.Linear(hidden, n_actions),
            )

        def forward(self, x):
            return self.net(x)


# ── numpy fallback Q-Network ─────────────────────────────
class QNetworkNumpy:
    """PyTorch 없을 때 사용하는 경량 numpy Q-Network."""
    def __init__(self, n_states: int, n_actions: int, hidden: int = 64):
        rng = np.random.default_rng(42)
        lim = np.sqrt(2.0 / n_states)
        self.W1 = rng.uniform(-lim, lim, (n_states, hidden)).astype(np.float32)
        self.b1 = np.zeros(hidden, dtype=np.float32)
        self.W2 = rng.uniform(-lim, lim, (hidden, hidden)).astype(np.float32)
        self.b2 = np.zeros(hidden, dtype=np.float32)
        self.W3 = rng.uniform(-lim, lim, (hidden, n_actions)).astype(np.float32)
        self.b3 = np.zeros(n_actions, dtype=np.float32)

    def forward(self, x: np.ndarray) -> np.ndarray:
        h1 = np.maximum(0, x @ self.W1 + self.b1)
        h2 = np.maximum(0, h1 @ self.W2 + self.b2)
        return h2 @ self.W3 + self.b3

    def copy_weights_from(self, other: "QNetworkNumpy"):
        self.W1 = other.W1.copy()
        self.b1 = other.b1.copy()
        self.W2 = other.W2.copy()
        self.b2 = other.b2.copy()
        self.W3 = other.W3.copy()
        self.b3 = other.b3.copy()


# ── State 전처리 ─────────────────────────────────────────
def _normalize_state(row: pd.Series) -> np.ndarray:
    """row → 정규화된 state vector (float32)."""
    vals = []
    scale = {
        "state_source_stock":      500.0,
        "state_target_stock":      500.0,
        "state_source_sales_30d":  1000.0,
        "state_target_sales_30d":  1000.0,
        "state_inbound_days":       90.0,
        "state_unit_cost":         5000.0,
        "state_distance_km":         20.0,
        "state_transfer_cost":    10000.0,
        "state_promotion_net_cost":5000.0,
    }
    for col in STATE_COLS:
        raw = float(row.get(col, 0.0) or 0.0)
        vals.append(raw / scale.get(col, 1.0))
    return np.clip(np.array(vals, dtype=np.float32), -10.0, 10.0)


def make_state_vectors(df: pd.DataFrame) -> np.ndarray:
    """DataFrame → state matrix (n_rows × N_STATES)."""
    for col in STATE_COLS:
        if col not in df.columns:
            df[col] = 0.0
    return np.stack([_normalize_state(row) for _, row in df.iterrows()])


# ── 메인 DQN 에이전트 ────────────────────────────────────
class TorchDQNAgent:
    """
    PyTorch / numpy 자동 전환 DQN 에이전트.

    기존 dqn_agent.py와 병렬로 운영.
    artifact 저장 형식: dqn_latest_model.npz (numpy 호환 유지)
    """

    def __init__(
        self,
        n_states:    int   = N_STATES,
        n_actions:   int   = N_ACTIONS,
        hidden:      int   = 64,
        lr:          float = 0.001,
        gamma:       float = 0.95,
        epsilon:     float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay:float= 0.995,
        batch_size:  int   = 64,
        buffer_size: int   = 10000,
        target_update:int  = 10,
    ):
        self.n_states     = n_states
        self.n_actions    = n_actions
        self.gamma        = gamma
        self.epsilon      = epsilon
        self.epsilon_min  = epsilon_min
        self.epsilon_decay= epsilon_decay
        self.batch_size   = batch_size
        self.target_update= target_update
        self.step_count   = 0
        self.backend      = "torch" if TORCH_AVAILABLE else "numpy"

        if TORCH_AVAILABLE:
            self.device   = torch.device("cpu")
            self.q_net    = QNetwork(n_states, n_actions, hidden).to(self.device)
            self.t_net    = QNetwork(n_states, n_actions, hidden).to(self.device)
            self.t_net.load_state_dict(self.q_net.state_dict())
            self.t_net.eval()
            self.optimizer = optim.Adam(self.q_net.parameters(), lr=lr)
            self.loss_fn   = nn.MSELoss()
        else:
            self.q_net  = QNetworkNumpy(n_states, n_actions, hidden)
            self.t_net  = QNetworkNumpy(n_states, n_actions, hidden)
            self.t_net.copy_weights_from(self.q_net)
            self.lr     = lr

        self.buffer  = ReplayBuffer(buffer_size)
        self.history = []   # {episode, loss, epsilon, mean_reward}

    # ── epsilon-greedy 액션 선택 ───────────────────────
    def select_action(self, state: np.ndarray) -> int:
        if np.random.rand() < self.epsilon:
            return np.random.randint(self.n_actions)
        return int(np.argmax(self._q_values(state)))

    def _q_values(self, state: np.ndarray) -> np.ndarray:
        if TORCH_AVAILABLE:
            with torch.no_grad():
                t = torch.FloatTensor(state).unsqueeze(0).to(self.device)
                return self.q_net(t).cpu().numpy()[0]
        else:
            return self.q_net.forward(state.reshape(1, -1))[0]

    # ── 학습 1 step ────────────────────────────────────
    def train_step(self) -> float:
        if len(self.buffer) < self.batch_size:
            return 0.0

        states, actions, rewards, next_states, dones = self.buffer.sample(self.batch_size)

        if TORCH_AVAILABLE:
            loss = self._train_step_torch(states, actions, rewards, next_states, dones)
        else:
            loss = self._train_step_numpy(states, actions, rewards, next_states, dones)

        self.step_count += 1
        if self.step_count % self.target_update == 0:
            self._update_target()

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return loss

    def _train_step_torch(self, states, actions, rewards, next_states, dones):
        s  = torch.FloatTensor(states).to(self.device)
        a  = torch.LongTensor(actions).to(self.device)
        r  = torch.FloatTensor(rewards).to(self.device)
        ns = torch.FloatTensor(next_states).to(self.device)
        d  = torch.FloatTensor(dones).to(self.device)

        q_cur  = self.q_net(s).gather(1, a.unsqueeze(1)).squeeze(1)
        with torch.no_grad():
            q_next = self.t_net(ns).max(1)[0]
        target = r + self.gamma * q_next * (1 - d)

        loss = self.loss_fn(q_cur, target)
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_net.parameters(), 1.0)
        self.optimizer.step()
        return float(loss.item())

    def _train_step_numpy(self, states, actions, rewards, next_states, dones):
        q_cur_all  = self.q_net.forward(states)
        q_next_all = self.t_net.forward(next_states)
        targets = q_cur_all.copy()

        for i in range(len(actions)):
            td_target = rewards[i] + self.gamma * q_next_all[i].max() * (1 - dones[i])
            targets[i, actions[i]] = td_target

        loss = float(np.mean((q_cur_all - targets) ** 2))

        # 올바른 역전파: W3 기울기는 h2.T @ grad (states.T 가 아님)
        grad_out = (q_cur_all - targets) * 2.0 / len(states)  # (batch, n_actions)
        h1 = np.maximum(0, states  @ self.q_net.W1 + self.q_net.b1)  # (batch, hidden)
        h2 = np.maximum(0, h1      @ self.q_net.W2 + self.q_net.b2)  # (batch, hidden)
        # W3: (hidden, n_actions) — h2.T(hidden,batch) @ grad_out(batch,n_actions)
        delta_W3 = h2.T @ grad_out                                    # (hidden, n_actions) ✓
        # gradient clipping — 폭주 방지
        max_grad = 1.0
        delta_W3 = np.clip(delta_W3, -max_grad, max_grad)
        self.q_net.W3 -= self.lr * delta_W3
        return loss

    def _update_target(self):
        if TORCH_AVAILABLE:
            self.t_net.load_state_dict(self.q_net.state_dict())
        else:
            self.t_net.copy_weights_from(self.q_net)

    # ── episode 기반 학습 루프 ─────────────────────────
    def train_episodes(
        self,
        df: pd.DataFrame,
        episodes:      int = 100,
        progress_fn    = None,  # streamlit.progress 콜백
    ) -> pd.DataFrame:
        """
        df: rl_training_log (state_*, action, reward 컬럼 포함)
        반환: history DataFrame (episode, loss, epsilon, mean_reward)
        """
        if df.empty:
            return pd.DataFrame()

        state_matrix = make_state_vectors(df)
        n_rows = len(df)

        for ep in range(1, episodes + 1):
            ep_rewards = []
            ep_losses  = []

            # 랜덤 순서로 샘플 순회
            idx_order = np.random.permutation(n_rows)

            for i in idx_order:
                state      = state_matrix[i]
                action_id  = self.select_action(state)
                # next state: 다음 인덱스 or 동일
                next_i     = (i + 1) % n_rows
                next_state = state_matrix[next_i]

                # reward: 기존 reward 컬럼 사용
                reward     = float(df["reward"].iloc[i])
                done       = (i == n_rows - 1)

                # Reward 정규화: Varo reward 값이 수만 단위 → [-10, 10] 클리핑
                reward_norm = float(np.clip(reward / 10000.0, -10.0, 10.0))
                self.buffer.push(state, action_id, reward_norm, next_state, done)
                loss = self.train_step()

                ep_rewards.append(reward)
                if loss > 0:
                    ep_losses.append(loss)

            mean_reward = float(np.mean(ep_rewards))
            mean_loss   = float(np.mean(ep_losses)) if ep_losses else 0.0

            record = {
                "episode":     ep,
                "loss":        round(mean_loss,   5),
                "epsilon":     round(self.epsilon, 4),
                "mean_reward": round(mean_reward,  3),
                "backend":     self.backend,
            }
            self.history.append(record)

            if progress_fn:
                progress_fn(ep / episodes, f"Episode {ep}/{episodes} | loss={mean_loss:.4f}")

        return pd.DataFrame(self.history)

    # ── 추천 결과 생성 ─────────────────────────────────
    def recommend(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        df → 각 행에 dqn_action, dqn_action_label, dqn_q_values 추가.
        기존 heuristic/greedy 컬럼 유지.
        """
        if df.empty:
            return df

        state_matrix = make_state_vectors(df.copy())
        result = df.copy()

        dqn_actions = []
        dqn_labels  = []
        dqn_qs      = []

        for i in range(len(state_matrix)):
            q_vals     = self._q_values(state_matrix[i])
            action_id  = int(np.argmax(q_vals))
            action_str = TORCH_ACTION_SPACE[action_id]
            dqn_actions.append(action_str)
            dqn_labels.append(_action_label_ko(action_str))
            dqn_qs.append(round(float(q_vals.max()), 4))

        result["dqn_action"]       = dqn_actions
        result["dqn_action_label"] = dqn_labels
        result["dqn_max_q"]        = dqn_qs
        result["dqn_backend"]      = self.backend
        return result

    # ── artifact 저장 (기존 형식 호환) ─────────────────
    def save(
        self,
        output_dir:        str   = "dqn_artifacts",
        sample_no:         str   = "",
        scenario_name:     str   = "",
        learning_rate:     float = 0.001,
        episodes:          int   = 0,
        candidate_count:   int   = 0,
        recommendations_df = None,  # 추천 결과 DataFrame
    ) -> dict:
        from pathlib import Path as _P
        from datetime import datetime as _dt

        out  = _P(output_dir); out.mkdir(parents=True, exist_ok=True)
        ts   = _dt.now().strftime("%Y%m%d_%H%M%S")

        def _fmt_sample(s):
            s = str(s).strip()
            if not s: return "sample00"
            if s.isdigit(): return f"sample{int(s):02d}"
            if s.startswith("sample") and s[6:].isdigit(): return f"sample{int(s[6:]):02d}"
            return s.lower()[:16]

        named = (f"dqn_{_fmt_sample(sample_no)}_{str(scenario_name).lower()[:12]}"
                 f"_lr{int(learning_rate*10000):04d}_{episodes}x{candidate_count}")

        history_df = pd.DataFrame(self.history) if self.history else pd.DataFrame()
        summary = {
            "backend":          self.backend,
            "n_states":         self.n_states,
            "n_actions":        self.n_actions,
            "episodes":         episodes,
            "training_samples": candidate_count,
            "candidate_count":  candidate_count,
            "final_loss":       float(history_df["loss"].iloc[-1]) if not history_df.empty else None,
            "final_epsilon":    float(self.epsilon),
            "sample_no":        sample_no,
            "scenario_name":    scenario_name,
            "created_at":       ts,
            "action_space":     TORCH_ACTION_SPACE,
        }

        def _save_set(prefix: str):
            # model weights → npz (기존 형식 호환)
            if TORCH_AVAILABLE:
                sd = self.q_net.state_dict()
                np.savez(
                    out / f"{prefix}_model.npz",
                    **{k: v.cpu().numpy() for k, v in sd.items()},
                    metadata=json.dumps(summary),
                )
            else:
                np.savez(
                    out / f"{prefix}_model.npz",
                    W1=self.q_net.W1, b1=self.q_net.b1,
                    W2=self.q_net.W2, b2=self.q_net.b2,
                    W3=self.q_net.W3, b3=self.q_net.b3,
                    metadata=json.dumps(summary),
                )
            if not history_df.empty:
                history_df.to_csv(out / f"{prefix}_history.csv", index=False, encoding="utf-8-sig")
            with open(out / f"{prefix}_summary.json", "w", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=2)
            if recommendations_df is not None and not recommendations_df.empty:
                recommendations_df.to_csv(
                    out / f"{prefix}_recommendations.csv", index=False, encoding="utf-8-sig"
                )

        _save_set("dqn_latest")   # 기존 최신 파일 덮어쓰기
        _save_set(named)          # 보관 파일

        # comparison CSV 누적
        comp_path = out / "dqn_training_comparison.csv"
        new_row = {
            "sample_no": sample_no, "scenario_name": scenario_name,
            "learning_rate": learning_rate, "episodes": episodes,
            "candidate_count": candidate_count,
            "final_loss":    summary["final_loss"],
            "final_epsilon": summary["final_epsilon"],
            "backend":       self.backend,
            "trained_at":    ts,
            "model_file":    str(out / f"{named}_model.npz"),
            "summary_file":  str(out / f"{named}_summary.json"),
        }
        if comp_path.exists():
            existing = pd.read_csv(comp_path, encoding="utf-8-sig")
            updated  = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)
        else:
            updated = pd.DataFrame([new_row])
        updated.to_csv(comp_path, index=False, encoding="utf-8-sig")

        return {
            "output_dir":      str(out),
            "named_prefix":    named,
            "summary":         summary,
            "history_rows":    len(history_df),
            "comparison_file": str(comp_path),
            "backend":         self.backend,
        }


# ── 한글 레이블 ─────────────────────────────────────────
def _action_label_ko(action_str: str) -> str:
    return {
        "keep_inventory":     "재고 유지",
        "discount_sale":      "할인 판매",
        "one_plus_one":       "1+1 프로모션",
        "direct_transfer":    "직접 이동",
        "dc_transfer":        "DC 경유 이동",
        "emergency_discount": "긴급 할인",
        "dispose":            "폐기",
    }.get(action_str, action_str)


# ── 편의 함수: 전체 학습+저장 ────────────────────────────
def run_torch_dqn(
    df:            pd.DataFrame,
    episodes:      int   = 100,
    lr:            float = 0.001,
    hidden:        int   = 64,
    batch_size:    int   = 64,
    output_dir:    str   = "dqn_artifacts",
    sample_no:     str   = "",
    scenario_name: str   = "",
    progress_fn          = None,
) -> tuple:
    """
    학습 → 추천 → 저장 원스톱.
    반환: (agent, recommend_df, history_df, save_result)
    """
    agent = TorchDQNAgent(
        lr=lr, hidden=hidden, batch_size=batch_size,
        epsilon=1.0, epsilon_min=0.05, epsilon_decay=0.99,
    )
    history_df   = agent.train_episodes(df, episodes=episodes, progress_fn=progress_fn)
    recommend_df = agent.recommend(df)
    save_result  = agent.save(
        output_dir=output_dir, sample_no=sample_no,
        scenario_name=scenario_name, learning_rate=lr,
        episodes=episodes, candidate_count=len(df),
        recommendations_df=recommend_df,
    )
    return agent, recommend_df, history_df, save_result
