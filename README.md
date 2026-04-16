# Visual Odometry Robustness Under Degraded Conditions

16-833 course project. A minimal monocular visual-odometry pipeline
evaluated on EuRoC MAV sequences under synthetic perceptual degradations.

## Scope pivot — honest note

The [proposal](./localization_project_proposal__2_%20%281%29.pdf) and
[interim report](./SLAM_Interim_Report_2.pdf) planned to benchmark three
full SLAM systems (ORB-SLAM3, Stella-VSLAM, DSO) on Google Colab. The
C++ build chain (Pangolin, g2o, DBoW2, FBoW, headless patches, stella's
examples-repo split) never produced a working pipeline despite several
weeks of iteration — see `SLAM_Benchmark_EuRoC_legacy.ipynb` for that
attempt.

This repo holds the rescoped experiment: the same scientific question
("which algorithmic choices fail under which degradation?") tackled with
a ~200-line Python VO pipeline where the independent variable is the
**feature detector** (ORB vs SIFT) and the dependent variable is
trajectory error under synthetic blur / low-light / noise. Everything is
pip-installable; no compilation.

## Files

| File | Purpose |
|---|---|
| `VO_Robustness_EuRoC.ipynb`        | The experiment. Run cells top to bottom. |
| `build_notebook.py`                 | Generator for the notebook — edit this, not the `.ipynb`. |
| `SLAM_Benchmark_EuRoC_legacy.ipynb` | Preserved record of the abandoned SLAM-systems attempt. |
| `SLAM_Interim_Report_2.pdf`         | Interim report (committed scope, pre-pivot). |
| `localization_project_proposal__2_ (1).pdf` | Original proposal. |

## Running locally

Tested on Windows 10, Python 3.11.

```bash
# from C:/Dev/slamproject
jupyter notebook VO_Robustness_EuRoC.ipynb
```

Cell 1 installs dependencies via `pip`. Cell 3 downloads EuRoC
`MH_01_easy` (≈1.2 GB) from ETH on first run; `V1_01_easy` downloads
when `QUICK_MODE = False` in cell 2.

Storage budget: ≈3 GB (datasets + a few MB of trajectories).

Runtime:
- `QUICK_MODE = True` (default): one sequence, stride-3 frames, 4
  degradations × 2 detectors = 8 runs ≈ 10 minutes.
- `QUICK_MODE = False`: both sequences, every frame, 10 degradations ×
  2 detectors = 40 runs ≈ 1 hour.

## What the experiment measures

For each `(sequence, detector, degradation)` triple:

- **ATE RMSE** — global trajectory error, Sim(3) aligned (`evo_ape tum
  --align --correct_scale`).
- **RPE RMSE** — local drift per step (`evo_rpe tum --align`, no scale
  correction).
- **Tracking success rate** — fraction of frames for which the VO
  produced a pose.
- **Per-frame wall time** — processing cost vs EuRoC's 50 ms real-time
  budget at 20 Hz.
- **Failure mode** — rule-based bucket: `success`, `minor_drift`,
  `tracking_divergence`, `tracking_loss`, `feature_starvation`,
  `performance_bottleneck`, `complete_failure`.

## Known limitations

These are flagged in the notebook and should appear in the final report:

1. **Scale is recovered from ground truth.** Each relative translation
   from `cv2.recoverPose` is rescaled by the magnitude of the GT
   inter-frame displacement. This is the standard pedagogical shortcut
   (e.g. Avi Singh's `monoVO-python`); it isolates matcher quality but
   means we do not evaluate scale recovery.
2. **No loop closure, no bundle adjustment.** Pure odometry. The
   "false_loop_closure" and "map_corruption" categories from the
   interim report's failure taxonomy are therefore dropped.
3. **Sim(3) ATE** averages out per-step scale drift within a trajectory.
   Low ATE implies correct shape up to a global scale factor, not
   correct absolute positions.
4. **Synthetic degradations ≠ real degradations.** Gaussian blur ≠
   direction-dependent motion blur; gamma darkening ignores the
   correlated sensor-noise increase at low light. Read the findings as
   statements about image-space transformations, not deployment-time
   conditions.
5. **Rolling shutter and textureless environments** from the interim
   report are not studied — they would require different datasets and
   VO-pipeline changes beyond the rescoped timeline.

## Regenerating the notebook

Edit `build_notebook.py` (cell contents are plain Python strings at
module scope), then:

```bash
python build_notebook.py
```

This rewrites `VO_Robustness_EuRoC.ipynb`. Don't edit the `.ipynb`
directly — changes won't survive the next regeneration.
