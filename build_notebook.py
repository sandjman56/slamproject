"""Generator for VO_Robustness_EuRoC.ipynb.

Running this script emits the notebook file next to it. Kept as a script so the
cell contents are readable as plain Python rather than JSON-escaped blobs.

Scope: rescoped project. The original plan was to benchmark ORB-SLAM3 /
Stella-VSLAM / DSO under degraded conditions; build-system pain forced a
pivot. The new experiment is a minimum-viable robustness study built on a
pure-Python monocular VO pipeline with ORB and SIFT, run on EuRoC easy
sequences under synthetic degradations (blur, low-light, noise). Everything
is pip-installable; no C++ builds.
"""
import json
import pathlib
import uuid

OUT = pathlib.Path(__file__).parent / "VO_Robustness_EuRoC.ipynb"

cells = []

def _id():
    return uuid.uuid4().hex[:12]

def md(text):
    cells.append({
        "cell_type": "markdown",
        "id": _id(),
        "metadata": {},
        "source": text.splitlines(keepends=True),
    })

def code(text):
    cells.append({
        "cell_type": "code",
        "id": _id(),
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.splitlines(keepends=True),
    })

# ---------------------------------------------------------------- Cell 0
md("""# Visual Odometry Robustness Under Degraded Conditions
**16-833 Project — Sander Schulman**

A minimal monocular visual odometry pipeline evaluated on EuRoC MAV
sequences under synthetic perceptual degradations. Compares feature
detectors (ORB vs SIFT) as the independent variable; the VO back-end is
held constant.

### Why this scope
The original proposal planned to benchmark three full SLAM systems
(ORB-SLAM3, Stella-VSLAM, DSO). Weeks of effort on the C++ build chain
(Pangolin, g2o, DBoW2, headless patches for Colab) did not produce a
working pipeline. This rescope swaps the *systems* axis for a *feature
detector* axis inside a single, controlled Python VO pipeline —
answering essentially the same scientific question ("which algorithmic
choices fail under which degradation?") with a tractable experiment.

### What runs here (local, Windows)
- Python 3.11, all deps via `pip` (no compilation).
- Downloads **MH_01_easy** and **V1_01_easy** from ETH (≈2.4 GB total).
- Applies synthetic Gaussian blur, gamma darkening, and Gaussian noise
  at three severities each.
- Runs a 2-frame monocular VO (ORB or SIFT + essential matrix + recoverPose)
  with GT-scaled per-step translation.
- Scores every (detector × degradation × sequence) run with `evo_ape`
  (ATE) and `evo_rpe` (RPE).
- Classifies each run into a failure-mode bucket.

### Limitations (called out in the writeup)
- VO is up-to-scale; each relative translation is rescaled by the GT
  inter-frame displacement magnitude (standard pedagogical shortcut,
  e.g. Avi Singh's `monoVO-python`). We therefore measure
  **direction + rotation accuracy** of the matcher, not scale recovery.
- ATE uses Sim(3) alignment (`evo --correct_scale`); per-step scale
  drift is averaged out. RPE is computed without scale correction.
- No loop closure, no bundle adjustment — this is *odometry*, not SLAM.

### Pipeline layout
```
C:/Dev/slamproject/
├── VO_Robustness_EuRoC.ipynb   ← this notebook
├── data/
│   └── euroc/
│       ├── MH_01_easy/mav0/... (cam0 images + sensor.yaml + state_gt)
│       └── V1_01_easy/mav0/...
└── results/
    ├── trajectories/           ← one TUM file per (seq, detector, degradation)
    └── eval/                   ← evo zips + combined results JSON + plots
```
""")

# ---------------------------------------------------------------- Cell 1
md("""---
## 1. Install dependencies

All pip wheels on Windows — no C++ toolchain needed.
`opencv-contrib-python` (not `opencv-python`) is required because SIFT
lives in `xfeatures2d`.
""")

code(r"""import subprocess, sys

PKGS = [
    'opencv-contrib-python==4.10.0.84',
    'numpy',
    'pandas',
    'matplotlib',
    'pyyaml',
    'tqdm',
    'evo==1.28.0',
]

def pip_install(pkgs):
    cmd = [sys.executable, '-m', 'pip', 'install', '-q'] + pkgs
    subprocess.run(cmd, check=True)

pip_install(PKGS)

import cv2, numpy, evo
print(f'OpenCV  : {cv2.__version__}')
print(f'NumPy   : {numpy.__version__}')
print(f'evo     : {evo.__version__ if hasattr(evo, "__version__") else "installed"}')
assert hasattr(cv2, 'SIFT_create'), 'SIFT not found — install opencv-contrib-python, not opencv-python'
print('SIFT    : OK')
""")

# ---------------------------------------------------------------- Cell 2
md("""---
## 2. Configuration

`QUICK_MODE = True` runs a reduced sweep (≈10 min on a laptop) — one
sequence, stride=3 (every third frame), 2 degradation levels. Flip to
`False` for the full sweep used in the final report (~1 hour).
""")

code(r"""from pathlib import Path

ROOT         = Path(r'C:/Dev/slamproject')
DATA_DIR     = ROOT / 'data' / 'euroc'
RESULTS_DIR  = ROOT / 'results'
TRAJ_DIR     = RESULTS_DIR / 'trajectories'
EVAL_DIR     = RESULTS_DIR / 'eval'
for d in (DATA_DIR, TRAJ_DIR, EVAL_DIR):
    d.mkdir(parents=True, exist_ok=True)

QUICK_MODE = True

SEQUENCES = ['MH_01_easy', 'V1_01_easy']
DETECTORS = ['ORB', 'SIFT']

# Frame stride — 1 = every frame, 3 = every 3rd (3x speedup, coarser trajectory)
FRAME_STRIDE = 3 if QUICK_MODE else 1

# Degradation sweep. Each entry: (label, kind, param).
#   blur:  Gaussian blur kernel sigma (pixels).
#   gamma: gamma > 1 -> darker; simulates low ambient light.
#   noise: additive Gaussian noise sigma on [0, 255] range.
DEGRADATIONS_FULL = [
    ('clean',        None,    None),
    ('blur_mild',    'blur',  2.0),
    ('blur_medium',  'blur',  4.0),
    ('blur_severe',  'blur',  8.0),
    ('dark_mild',    'gamma', 1.8),
    ('dark_medium',  'gamma', 2.8),
    ('dark_severe',  'gamma', 4.5),
    ('noise_mild',   'noise', 10.0),
    ('noise_medium', 'noise', 25.0),
    ('noise_severe', 'noise', 50.0),
]
DEGRADATIONS_QUICK = [
    ('clean',        None,    None),
    ('blur_severe',  'blur',  8.0),
    ('dark_severe',  'gamma', 4.5),
    ('noise_severe', 'noise', 50.0),
]
DEGRADATIONS = DEGRADATIONS_QUICK if QUICK_MODE else DEGRADATIONS_FULL

# VO parameters
N_FEATURES      = 2000       # max keypoints per frame
LOWE_RATIO      = 0.75       # Lowe ratio test
RANSAC_THRESH   = 1.0        # pixels, for findEssentialMat
MIN_MATCHES     = 15         # below this, drop the frame (tracking fail)
REALTIME_MS     = 50.0       # EuRoC cam0 runs at 20 Hz = 50 ms budget

print(f'QUICK_MODE     : {QUICK_MODE}')
print(f'Sequences      : {SEQUENCES if not QUICK_MODE else SEQUENCES[:1]}')
print(f'Detectors      : {DETECTORS}')
print(f'Degradations   : {[d[0] for d in DEGRADATIONS]}')
print(f'Frame stride   : {FRAME_STRIDE}')
run_seqs = SEQUENCES[:1] if QUICK_MODE else SEQUENCES
total_runs = len(run_seqs) * len(DETECTORS) * len(DEGRADATIONS)
print(f'Total runs     : {total_runs}')
""")

# ---------------------------------------------------------------- Cell 3
md("""---
## 3. Download EuRoC sequences

Downloads each sequence as a zip, then unzips it. Skips any sequence
already unpacked. ~1.2 GB per sequence.

**Mirrors.** The official host (`robotics.ethz.ch`) has chronic
multi-hour outages. We fall back to dated snapshots on the Wayback
Machine (`web.archive.org`). Bytes are identical — the snapshot is
just a read-through CDN capture of the same file. Wayback can stall
for 60–90 s at the start of each request while it resolves the
capture, so we use `curl -C -` (resumable, handles slow servers)
and retry each URL a few times before moving to the next.

Expect 5–15 minutes per sequence from the Wayback mirror.
""")

code(r"""import subprocess, shutil, zipfile, time
from pathlib import Path

# Each sequence -> list of URLs tried in order. First entry is the
# authoritative ETH host; remaining entries are Wayback captures at
# different timestamps (any one of which points at the same bytes,
# but archive.org sometimes 404s a capture while serving another fine).
EUROC_MIRRORS = {
    'MH_01_easy': [
        'http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/machine_hall/MH_01_easy/MH_01_easy.zip',
        'https://web.archive.org/web/20230331114522/http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/machine_hall/MH_01_easy/MH_01_easy.zip',
        'https://web.archive.org/web/2022/http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/machine_hall/MH_01_easy/MH_01_easy.zip',
        'https://web.archive.org/web/2021/http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/machine_hall/MH_01_easy/MH_01_easy.zip',
    ],
    'V1_01_easy': [
        'http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/vicon_room1/V1_01_easy/V1_01_easy.zip',
        'https://web.archive.org/web/2023/http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/vicon_room1/V1_01_easy/V1_01_easy.zip',
        'https://web.archive.org/web/2022/http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/vicon_room1/V1_01_easy/V1_01_easy.zip',
        'https://web.archive.org/web/2021/http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/vicon_room1/V1_01_easy/V1_01_easy.zip',
    ],
}

# Sanity-check sizes (bytes) — downloads smaller than this are treated as
# a failed capture (404 HTML bodies, empty redirects, etc.)
MIN_ZIP_BYTES = 100 * 1024 * 1024  # 100 MB

def _try_curl(url, dst, attempts=3, connect_timeout=20, speed_low=1024, speed_time=120):
    '''Resumable download with curl. Retries in-place on partial transfer.
    Returns True on success.

    - `-C -` resumes at current file size, so partial transfers are retained
      across retries.
    - `--speed-limit/--speed-time` aborts if throughput drops below
      `speed_low` B/s for `speed_time` s (catches frozen Wayback streams).
    '''
    for attempt in range(1, attempts + 1):
        prefix = f'    [attempt {attempt}/{attempts}]'
        cmd = [
            'curl', '-L', '--fail',
            '-C', '-',                                  # resume if partial
            '--connect-timeout', str(connect_timeout),
            '--speed-limit', str(speed_low),
            '--speed-time',  str(speed_time),
            '--retry', '0',
            '-A', 'slamproject/1.0',
            '-o', str(dst),
            url,
        ]
        print(prefix, '->', url[:90] + ('...' if len(url) > 90 else ''))
        t0 = time.time()
        rc = subprocess.call(cmd)
        dt = time.time() - t0
        sz = dst.stat().st_size if dst.exists() else 0
        print(f'{prefix} rc={rc}  size={sz/1e6:.1f} MB  elapsed={dt:.0f}s')
        if rc == 0 and sz >= MIN_ZIP_BYTES:
            return True
        # Curl exit codes worth retrying the same URL on:
        # 18=partial, 28=timeout, 56=recv failure, 92=HTTP/2 stream error
        if rc in (18, 28, 56, 92):
            print(f'{prefix} partial/timeout — will retry same URL')
            continue
        # Other failures: move on to next mirror
        break
    return False

def download_with_fallback(seq, dst):
    for i, url in enumerate(EUROC_MIRRORS[seq]):
        host = url.split('/')[2]
        print(f'  [mirror {i+1}/{len(EUROC_MIRRORS[seq])}] {host}')
        if _try_curl(url, dst):
            return url
        print(f'  [mirror {i+1}] failed — trying next')
        if dst.exists() and dst.stat().st_size < MIN_ZIP_BYTES:
            dst.unlink()
    raise RuntimeError(
        f'All mirrors failed for {seq}. If this persists, download manually '
        f'from https://projects.asl.ethz.ch/datasets/euroc-mav/ and place '
        f'the zip at {dst}'
    )

run_seqs = SEQUENCES[:1] if QUICK_MODE else SEQUENCES
for seq in run_seqs:
    seq_dir = DATA_DIR / seq
    if (seq_dir / 'mav0' / 'cam0' / 'data').is_dir():
        n = len(list((seq_dir / 'mav0' / 'cam0' / 'data').glob('*.png')))
        print(f'[SKIP] {seq}: already unpacked ({n} frames)')
        continue

    zip_path = DATA_DIR / f'{seq}.zip'
    print(f'[DL]   {seq}')
    t0 = time.time()
    src_url = download_with_fallback(seq, zip_path)
    print(f'[UNZIP] {seq}')
    seq_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(seq_dir)
    zip_path.unlink()
    n = len(list((seq_dir / 'mav0' / 'cam0' / 'data').glob('*.png')))
    print(f'[OK]   {seq}: {n} frames in {time.time()-t0:.0f}s  (from {src_url.split("/")[2]})')
""")

# ---------------------------------------------------------------- Cell 4
md("""---
## 4. Load calibration + ground truth per sequence

For each sequence: parse `sensor.yaml` for the pinhole intrinsics and
radial-tangential distortion, and convert the Vicon ground-truth CSV
to TUM format (`ts x y z qx qy qz qw`). GT is at 200 Hz; we keep full
resolution and nearest-neighbour-lookup per cam0 timestamp at eval time.
""")

code(r"""import yaml
import pandas as pd
import numpy as np

def load_calib(seq):
    path = DATA_DIR / seq / 'mav0' / 'cam0' / 'sensor.yaml'
    cfg  = yaml.safe_load(path.read_text())
    fx, fy, cx, cy = cfg['intrinsics']
    k1, k2, p1, p2 = cfg['distortion_coefficients']
    W, H           = cfg['resolution']
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    D = np.array([k1, k2, p1, p2], dtype=np.float64)
    return {'K': K, 'D': D, 'W': W, 'H': H}

def euroc_gt_to_tum(seq, force=False):
    src = DATA_DIR / seq / 'mav0' / 'state_groundtruth_estimate0' / 'data.csv'
    dst = DATA_DIR / seq / 'gt.tum'
    if dst.exists() and not force:
        return dst
    df = pd.read_csv(src, comment='#', header=None)
    # EuRoC columns: ts(ns), px,py,pz, qw,qx,qy,qz, vx,vy,vz, wx,wy,wz, ax,ay,az
    out = pd.DataFrame({
        'ts': df.iloc[:, 0].astype('int64') / 1e9,
        'x':  df.iloc[:, 1], 'y':  df.iloc[:, 2], 'z':  df.iloc[:, 3],
        'qx': df.iloc[:, 5], 'qy': df.iloc[:, 6], 'qz': df.iloc[:, 7],
        'qw': df.iloc[:, 4],
    })
    out.to_csv(dst, sep=' ', header=False, index=False, float_format='%.9f')
    return dst

def list_cam0_frames(seq):
    img_dir = DATA_DIR / seq / 'mav0' / 'cam0' / 'data'
    frames  = sorted(img_dir.glob('*.png'))
    # EuRoC filenames are timestamps in nanoseconds
    ts      = np.array([int(p.stem) / 1e9 for p in frames], dtype=np.float64)
    return frames, ts

run_seqs = SEQUENCES[:1] if QUICK_MODE else SEQUENCES
SEQ_META = {}
for seq in run_seqs:
    calib = load_calib(seq)
    gt_path = euroc_gt_to_tum(seq)
    frames, ts = list_cam0_frames(seq)
    gt_df = pd.read_csv(gt_path, sep=' ', header=None,
                        names=['ts','x','y','z','qx','qy','qz','qw'])
    SEQ_META[seq] = {'calib': calib, 'gt_path': gt_path, 'gt_df': gt_df,
                     'frames': frames, 'ts': ts}
    print(f'{seq}: {len(frames)} cam0 frames, {len(gt_df)} GT poses, '
          f'K={calib["K"][0,0]:.1f}|{calib["K"][1,1]:.1f}')
""")

# ---------------------------------------------------------------- Cell 5
md("""---
## 5. Degradation functions

Each function takes a grayscale `uint8` image and returns a degraded
`uint8` image of the same shape.

- **Gaussian blur** — proxies motion blur at increasing severity.
- **Gamma darkening** — `out = 255 * (in/255)^γ`, γ > 1 reduces midtones,
  simulates low ambient light.
- **Gaussian noise** — additive zero-mean noise, simulates high sensor gain.
""")

code(r"""import cv2
import numpy as np

_rng = np.random.default_rng(42)

def degrade(img, kind, param):
    '''img: uint8 grayscale. Returns uint8 grayscale.'''
    if kind is None:
        return img
    if kind == 'blur':
        ksize = max(3, int(2 * round(3 * param) + 1))
        return cv2.GaussianBlur(img, (ksize, ksize), param)
    if kind == 'gamma':
        lut = np.power(np.arange(256) / 255.0, param) * 255.0
        return cv2.LUT(img, lut.astype(np.uint8))
    if kind == 'noise':
        noise = _rng.normal(0, param, img.shape)
        return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    raise ValueError(f'unknown degradation kind {kind!r}')


# --- visual sanity check ---
import matplotlib.pyplot as plt

seq0 = list(SEQ_META)[0]
sample = cv2.imread(str(SEQ_META[seq0]['frames'][200]), cv2.IMREAD_GRAYSCALE)

fig, axes = plt.subplots(1, len(DEGRADATIONS), figsize=(3 * len(DEGRADATIONS), 3))
if len(DEGRADATIONS) == 1:
    axes = [axes]
for ax, (label, kind, param) in zip(axes, DEGRADATIONS):
    d = degrade(sample, kind, param)
    ax.imshow(d, cmap='gray', vmin=0, vmax=255)
    ax.set_title(label, fontsize=9)
    ax.axis('off')
plt.tight_layout()
plt.savefig(EVAL_DIR / 'degradation_examples.png', dpi=120, bbox_inches='tight')
plt.show()
""")

# ---------------------------------------------------------------- Cell 6
md("""---
## 6. Monocular VO pipeline

2-frame essential-matrix VO:

1. Load frame *i*, undistort with sequence intrinsics + distortion.
2. Apply degradation (if any) in the undistorted image plane.
3. Detect + describe keypoints with the chosen detector.
4. Match to the previous successfully-tracked frame with BFMatcher +
   Lowe ratio test.
5. `findEssentialMat` (RANSAC) then `recoverPose` → relative rotation `R`
   and unit-norm translation direction `t`.
6. Scale `t` by the GT inter-frame translation magnitude between the
   two frames (nearest GT timestamp lookup). This is the pedagogical
   shortcut that lets us measure matcher quality rather than
   scale-recovery quality.
7. Chain into a cumulative pose; emit one TUM row per tracked frame.

If any step fails (too few matches, degenerate `E`), the frame is
*dropped*: the previous reference stays put and we try again next frame.
The fraction of frames that produce a pose is the **tracking success rate**.
""")

code(r"""import cv2, time, numpy as np
from scipy.spatial.transform import Rotation as Rscipy

def _create_detector(name):
    if name == 'ORB':
        return cv2.ORB_create(nfeatures=N_FEATURES), cv2.NORM_HAMMING
    if name == 'SIFT':
        return cv2.SIFT_create(nfeatures=N_FEATURES), cv2.NORM_L2
    raise ValueError(name)

def _nearest_gt_pos(gt_df, ts):
    # returns (x,y,z) at the GT row whose timestamp is closest to ts
    i = int(np.argmin(np.abs(gt_df['ts'].values - ts)))
    r = gt_df.iloc[i]
    return np.array([r['x'], r['y'], r['z']], dtype=np.float64)

def run_vo(seq, detector_name, degradation, stride=1, verbose=False):
    '''Returns (tum_rows, stats) where tum_rows is a list of
    [ts, x, y, z, qx, qy, qz, qw] and stats is a dict.'''
    meta   = SEQ_META[seq]
    K, D   = meta['calib']['K'], meta['calib']['D']
    frames = meta['frames'][::stride]
    ts_all = meta['ts'][::stride]
    gt_df  = meta['gt_df']
    det, norm = _create_detector(detector_name)
    bf = cv2.BFMatcher(norm, crossCheck=False)

    tum_rows = []
    # Cumulative camera pose in world frame (cam0 = world origin)
    R_cum = np.eye(3)
    t_cum = np.zeros(3)

    # First frame is the anchor: emit identity pose.
    first_img = cv2.imread(str(frames[0]), cv2.IMREAD_GRAYSCALE)
    first_img = cv2.undistort(first_img, K, D)
    first_img = degrade(first_img, degradation[1], degradation[2])
    prev_kp, prev_des = det.detectAndCompute(first_img, None)
    prev_ts = ts_all[0]
    prev_gt_pos = _nearest_gt_pos(gt_df, prev_ts)
    q = Rscipy.from_matrix(R_cum).as_quat()  # xyzw
    tum_rows.append([prev_ts, *t_cum.tolist(), *q.tolist()])

    n_total    = len(frames) - 1   # pairs attempted
    n_tracked  = 0                 # pairs that emitted a pose
    n_low_match = 0
    n_bad_E    = 0
    t_start = time.time()

    for i in range(1, len(frames)):
        img = cv2.imread(str(frames[i]), cv2.IMREAD_GRAYSCALE)
        img = cv2.undistort(img, K, D)
        img = degrade(img, degradation[1], degradation[2])
        kp, des = det.detectAndCompute(img, None)
        cur_ts  = ts_all[i]

        if des is None or prev_des is None or len(kp) < MIN_MATCHES:
            n_low_match += 1
            continue

        pairs = bf.knnMatch(prev_des, des, k=2)
        good = [p[0] for p in pairs
                if len(p) == 2 and p[0].distance < LOWE_RATIO * p[1].distance]
        if len(good) < MIN_MATCHES:
            n_low_match += 1
            continue

        pts_prev = np.float32([prev_kp[m.queryIdx].pt for m in good])
        pts_cur  = np.float32([kp[m.trainIdx].pt      for m in good])

        E, mask = cv2.findEssentialMat(
            pts_prev, pts_cur, K, method=cv2.RANSAC,
            prob=0.999, threshold=RANSAC_THRESH)
        if E is None or E.shape != (3, 3):
            n_bad_E += 1
            continue

        n_in, R_rel, t_rel, _ = cv2.recoverPose(E, pts_prev, pts_cur, K, mask=mask)
        if n_in < MIN_MATCHES:
            n_bad_E += 1
            continue

        cur_gt_pos = _nearest_gt_pos(gt_df, cur_ts)
        scale      = float(np.linalg.norm(cur_gt_pos - prev_gt_pos))

        # Chain: R_cum and t_cum describe camera pose in world frame.
        # recoverPose returns (R_rel, t_rel) mapping prev-cam coords -> cur-cam coords.
        # So the cur-cam origin, expressed in prev-cam frame, is -R_rel^T @ t_rel.
        t_unit_in_prev = -R_rel.T @ t_rel.ravel()
        t_cum = t_cum + R_cum @ (scale * t_unit_in_prev)
        R_cum = R_cum @ R_rel.T

        q = Rscipy.from_matrix(R_cum).as_quat()  # xyzw
        tum_rows.append([cur_ts, *t_cum.tolist(), *q.tolist()])

        prev_kp, prev_des = kp, des
        prev_ts    = cur_ts
        prev_gt_pos = cur_gt_pos
        n_tracked  += 1

    wall_s  = time.time() - t_start
    stats = {
        'n_frames_input': len(frames),
        'n_pairs':        n_total,
        'n_tracked':      n_tracked,
        'n_low_match':    n_low_match,
        'n_bad_E':        n_bad_E,
        'tracking_rate':  (n_tracked / n_total) if n_total else 0.0,
        'wall_s':         wall_s,
        'per_frame_ms':   (wall_s * 1000.0 / len(frames)) if frames else None,
    }
    return tum_rows, stats

def write_tum(path, rows):
    with open(path, 'w') as f:
        for r in rows:
            f.write(' '.join(f'{v:.9f}' for v in r) + '\n')

# smoke test: quick run on the first few hundred frames
_seq = list(SEQ_META)[0]
_rows, _stats = run_vo(_seq, 'ORB', ('clean', None, None), stride=max(FRAME_STRIDE, 5))
print(f'Smoke test ({_seq}, ORB, clean, stride=5):')
for k, v in _stats.items():
    print(f'  {k:16s} = {v}')
print(f'  rows written    = {len(_rows)}')
""")

# ---------------------------------------------------------------- Cell 7
md("""---
## 7. Run the full sweep

One TUM file per `(sequence, detector, degradation)` cell in
`results/trajectories/`. All runs together should finish in ≈10 min
under `QUICK_MODE` or ~1 h for the full sweep.
""")

code(r"""import json
from tqdm.auto import tqdm

run_seqs = SEQUENCES[:1] if QUICK_MODE else SEQUENCES

sweep_log = []
triples = [(s, d, deg) for s in run_seqs for d in DETECTORS for deg in DEGRADATIONS]

for seq, detector, deg in tqdm(triples, desc='VO sweep'):
    label = deg[0]
    out_path = TRAJ_DIR / f'{seq}__{detector}__{label}.tum'
    if out_path.exists() and out_path.stat().st_size > 0:
        # idempotent: skip completed cells when re-running
        n_rows = sum(1 for _ in open(out_path))
        sweep_log.append({
            'seq': seq, 'detector': detector, 'degradation': label,
            'traj_path': str(out_path), 'n_rows': n_rows, 'skipped': True,
        })
        continue

    rows, stats = run_vo(seq, detector, deg, stride=FRAME_STRIDE)
    write_tum(out_path, rows)
    sweep_log.append({
        'seq': seq, 'detector': detector, 'degradation': label,
        'traj_path': str(out_path), 'n_rows': len(rows), 'skipped': False,
        **stats,
    })

log_path = EVAL_DIR / 'sweep_log.json'
log_path.write_text(json.dumps(sweep_log, indent=2))
print(f'\nWrote {len(sweep_log)} entries to {log_path}')
""")

# ---------------------------------------------------------------- Cell 8
md("""---
## 8. Evaluate every run with `evo`

`evo_ape` with `--align --correct_scale` (Sim(3) alignment) for ATE.
`evo_rpe` *without* scale correction for RPE (local per-step metric;
scale correction isn't meaningful for it).
""")

code(r"""import subprocess, json, zipfile

def run_evo(metric, gt_tum, est_tum, out_zip, sim3=True):
    binary = f'evo_{metric}'
    cmd = [binary, 'tum', str(gt_tum), str(est_tum), '--align']
    if sim3 and metric == 'ape':
        cmd.append('--correct_scale')
    cmd += ['--save_results', str(out_zip), '--no_warnings']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if not out_zip.exists():
        return None
    try:
        with zipfile.ZipFile(out_zip) as zf:
            with zf.open('stats.json') as sf:
                stats = json.load(sf)
        return float(stats.get('rmse'))
    except Exception:
        return None


def classify(ate, rpe, tracking_rate, per_frame_ms):
    '''Data-driven failure taxonomy, adapted from the interim report.

    Applied in order, first match wins. Categories without a loop closure
    module ("false_loop_closure", "map_corruption") are dropped since
    this VO has neither.
    '''
    if ate is None or tracking_rate == 0:
        return 'complete_failure'
    if tracking_rate < 0.30:
        return 'feature_starvation'
    if tracking_rate < 0.80:
        return 'tracking_loss'
    if per_frame_ms is not None and per_frame_ms > REALTIME_MS:
        return 'performance_bottleneck'
    if ate > 2.0:
        return 'tracking_divergence'
    if ate > 0.5:
        return 'minor_drift'
    return 'success'


sweep_log = json.loads((EVAL_DIR / 'sweep_log.json').read_text())
results = []
for entry in sweep_log:
    seq     = entry['seq']
    det     = entry['detector']
    deg     = entry['degradation']
    traj    = Path(entry['traj_path'])
    gt_tum  = SEQ_META[seq]['gt_path']

    ate_zip = EVAL_DIR / f'{seq}__{det}__{deg}__ape.zip'
    rpe_zip = EVAL_DIR / f'{seq}__{det}__{deg}__rpe.zip'
    ate = run_evo('ape', gt_tum, traj, ate_zip, sim3=True)
    rpe = run_evo('rpe', gt_tum, traj, rpe_zip, sim3=False)

    tracking_rate = entry.get('tracking_rate')
    if tracking_rate is None:
        # Row was skipped (already-computed file). Re-derive from N frames.
        frames = SEQ_META[seq]['frames'][::FRAME_STRIDE]
        tracking_rate = (entry['n_rows'] - 1) / max(len(frames) - 1, 1)

    per_frame_ms = entry.get('per_frame_ms')
    label = classify(ate, rpe, tracking_rate, per_frame_ms)

    results.append({
        'seq': seq, 'detector': det, 'degradation': deg,
        'ate_rmse': ate, 'rpe_rmse': rpe,
        'tracking_rate': tracking_rate,
        'per_frame_ms': per_frame_ms,
        'failure_mode': label,
        'traj_rows': entry['n_rows'],
    })

    print(f'{seq:14s} {det:4s} {deg:14s}  '
          f'ATE={ate if ate is None else f"{ate:6.3f}":>7s}  '
          f'RPE={rpe if rpe is None else f"{rpe:6.3f}":>7s}  '
          f'track={tracking_rate:5.1%}  '
          f'-> {label}')

(EVAL_DIR / 'all_results.json').write_text(json.dumps(results, indent=2))
print(f'\nWrote {EVAL_DIR / "all_results.json"}')
""")

# ---------------------------------------------------------------- Cell 9
md("""---
## 9. Results: tables and plots

- Pivot table of ATE RMSE per `(detector × degradation)` per sequence.
- Bar plots of ATE vs degradation level.
- Failure-mode heatmap.
""")

code(r"""import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

results = json.loads((EVAL_DIR / 'all_results.json').read_text())
df = pd.DataFrame(results)

# --- Pivot: ATE per (seq, detector, degradation) ---
for seq in df['seq'].unique():
    sub = df[df['seq'] == seq]
    pt = sub.pivot(index='degradation', columns='detector', values='ate_rmse')
    pt = pt.reindex([d[0] for d in DEGRADATIONS])
    print(f'\nATE RMSE (m) — {seq}')
    print(pt.to_string(float_format=lambda v: f'{v:6.3f}' if pd.notnull(v) else '   —  '))

# --- Failure-mode table ---
print('\nFailure mode per (seq, detector, degradation):')
fm = df.pivot_table(index=['seq', 'degradation'], columns='detector',
                    values='failure_mode', aggfunc='first')
fm = fm.reindex([(s, d[0]) for s in df['seq'].unique() for d in DEGRADATIONS])
print(fm.to_string())

# --- Plots ---
deg_labels = [d[0] for d in DEGRADATIONS]
fig, axes = plt.subplots(2, 2, figsize=(13, 8))
colors = {'ORB': '#2196F3', 'SIFT': '#FF9800'}

for ax, metric, ylabel in [
    (axes[0, 0], 'ate_rmse',      'ATE RMSE (m)'),
    (axes[0, 1], 'rpe_rmse',      'RPE RMSE (m)'),
    (axes[1, 0], 'tracking_rate', 'Tracking success rate'),
    (axes[1, 1], 'per_frame_ms',  'Per-frame time (ms)'),
]:
    x = np.arange(len(deg_labels))
    width = 0.8 / max(len(DETECTORS), 1)
    for i, det in enumerate(DETECTORS):
        sub = df[df['detector'] == det].groupby('degradation')[metric].mean()
        vals = [sub.get(lbl, 0) or 0 for lbl in deg_labels]
        ax.bar(x + i * width - 0.4 + width / 2, vals, width,
               label=det, color=colors.get(det))
    ax.set_xticks(x)
    ax.set_xticklabels(deg_labels, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel(ylabel)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

axes[1, 1].axhline(REALTIME_MS, color='red', ls='--', lw=1, alpha=0.6)
plt.tight_layout()
fig_path = EVAL_DIR / 'comparison_plot.png'
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.show()
print(f'\nPlot saved -> {fig_path}')
""")

# ---------------------------------------------------------------- Cell 10
md("""---
## 10. Notes & limitations

- **Scale recovery is cheated via GT** — each inter-frame translation is
  scaled by the magnitude of the ground-truth translation over the same
  interval. This isolates detector/matcher robustness; a proper
  pipeline would recover scale from triangulated map points.
- **No loop closure, no bundle adjustment** — this is pure odometry. The
  interim report's "false_loop_closure" and "map_corruption" categories
  are therefore dropped from the taxonomy.
- **Sim(3) ATE** averages out per-step scale drift, so an ATE of zero
  does not imply perfect scale; it implies correct *shape* up to a
  single global scale factor.
- **Synthetic degradations ≠ real degradations.** Gaussian blur is a
  coarse proxy for motion blur (real motion blur is direction-dependent
  and exposure-dependent). Gamma darkening ignores sensor-noise increase
  at low light. Findings should be read as "these detectors respond to
  these image transformations in these ways" — not as strong claims
  about deployment-time behaviour.
- **Rolling shutter, textureless environments** from the proposal are
  not studied here — would require datasets and VO changes beyond scope.

### Running the full sweep
Flip `QUICK_MODE = False` in cell 2 and re-run from cell 3 onwards
(downloads the second sequence and runs the 10-level degradation sweep).
Total runtime ≈ 1 h on a recent laptop.

### Regenerating this notebook
Edit `build_notebook.py` and run:

```bash
python build_notebook.py
```

That rewrites `VO_Robustness_EuRoC.ipynb` from the cell strings in the
generator. Keep the generator — editing the notebook JSON directly is
painful and won't survive the next regeneration.
""")

# ---------------------------------------------------------------- Emit notebook
notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

with OUT.open('w', encoding='utf-8', newline='\n') as f:
    json.dump(notebook, f, indent=1, ensure_ascii=False)
    f.write('\n')

print(f'Wrote {OUT}  ({OUT.stat().st_size:,} bytes, {len(cells)} cells)')
