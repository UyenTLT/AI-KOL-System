#!/usr/bin/env python3
"""Standalone re-implementation of RVC WebUI's `train_index` button handler.

This checkout's index build only exists as a Gradio click-handler closure inside
infer-web.py, with no CLI entry point — unlike the other four stages, which are real
`python -m` modules. This extracts that same logic (feature concat -> optional k-means ->
faiss IVF-Flat, trained then filled) so train_rvc.py has a script to shell out to.

    python _rvc_build_index.py <exp_dir> <version> <index_out_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import faiss


def main() -> int:
    exp_dir1, version, index_out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    exp_dir = Path("logs") / exp_dir1
    feature_dir = exp_dir / ("3_feature256" if version == "v1" else "3_feature768")
    names = sorted(p.name for p in feature_dir.glob("*.npy"))
    if not names:
        raise SystemExit(f"no features in {feature_dir} — run the feature stage first")

    big_npy = np.concatenate([np.load(feature_dir / n) for n in names], 0)
    rng = np.random.default_rng()
    big_npy = big_npy[rng.permutation(big_npy.shape[0])]

    if big_npy.shape[0] > 2e5:
        from sklearn.cluster import MiniBatchKMeans
        print(f"k-means: {big_npy.shape[0]} rows -> 10000 centers")
        big_npy = MiniBatchKMeans(n_clusters=10000, batch_size=256, compute_labels=False,
                                  init="random").fit(big_npy).cluster_centers_

    np.save(exp_dir / "total_fea.npy", big_npy)
    n_ivf = min(int(16 * np.sqrt(big_npy.shape[0])), big_npy.shape[0] // 39)
    print(f"{big_npy.shape}, n_ivf={n_ivf}")

    dim = 256 if version == "v1" else 768
    index = faiss.index_factory(dim, f"IVF{n_ivf},Flat")
    index_ivf = faiss.extract_index_ivf(index)
    index_ivf.nprobe = 1
    print("training index...")
    index.train(big_npy)
    trained = exp_dir / f"trained_IVF{n_ivf}_Flat_nprobe_1_{exp_dir1}_{version}.index"
    faiss.write_index(index, str(trained))

    print("adding vectors...")
    for i in range(0, big_npy.shape[0], 8192):
        index.add(big_npy[i:i + 8192])
    added_name = f"added_IVF{n_ivf}_Flat_nprobe_1_{exp_dir1}_{version}.index"
    added = exp_dir / added_name
    faiss.write_index(index, str(added))

    index_out.mkdir(parents=True, exist_ok=True)
    external = index_out / f"{exp_dir1}_IVF{n_ivf}_Flat_nprobe_1_{exp_dir1}_{version}.index"
    external.write_bytes(added.read_bytes())
    print(f"index -> {external}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
