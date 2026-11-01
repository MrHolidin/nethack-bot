import sys, statistics as st, multiprocessing as mp
import numpy as np, nle.nethack as nh
from nle.env.tasks import NetHackScore

def play(seed):
    env = NetHackScore(character="@", actions=nh.ACTIONS, allow_all_yn_questions=True, allow_all_modes=True,
                       max_episode_steps=50_000, penalty_step=0.0, penalty_time=0.0)
    env.seed(core=seed, disp=seed, reseed=False)
    obs, _ = env.reset()
    rng = np.random.default_rng(seed)
    total, depth = 0.0, 1
    for _ in range(50_000):
        obs, r, term, trunc, _ = env.step(int(rng.integers(env.action_space.n)))
        total += r
        if not (term or trunc):
            depth = max(depth, int(obs["blstats"][nh.NLE_BL_DEPTH]))
        if term or trunc:
            break
    return total, depth

if __name__ == "__main__":
    with mp.Pool(2) as p:
        res = p.map(play, range(1000, 1100))
    sc = [r[0] for r in res]; dp = [r[1] for r in res]
    print(f"random: score mean {st.mean(sc):.1f} median {st.median(sc)} max {max(sc)} | depth mean {st.mean(dp):.2f} max {max(dp)}")
