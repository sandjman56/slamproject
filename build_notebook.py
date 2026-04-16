"""Generator for SLAM_Benchmark_EuRoC.ipynb.

Running this script emits the notebook file next to it. Kept as a script so the
cell contents are readable as plain Python/bash rather than JSON-escaped blobs.
"""
import json
import pathlib
import uuid

OUT = pathlib.Path(__file__).parent / "SLAM_Benchmark_EuRoC.ipynb"

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
md("""# Visual SLAM Benchmarking Under Degraded Conditions
**16-833 Project — Sander Schulman**

Benchmarks **ORB-SLAM3**, **Stella-VSLAM**, and **DSO** (best-effort) on six
EuRoC MAV sequences spanning three difficulty levels. Runs on **Google Colab
or Kaggle Notebooks** — the platform is auto-detected in cell 1.

### How to use (Colab)
1. **Runtime → Change runtime type → any CPU/GPU instance** (GPU not required, just gives more RAM).
2. Run cells **in order**. Cold start build time: ~30–40 min.
3. Cells are idempotent — after a session timeout, re-run from the top.
4. Trajectory outputs are checkpointed to Google Drive after every sequence.

### How to use (Kaggle)
1. **Settings panel → Accelerator: None** (or GPU for more RAM), **Internet: On**.
2. Optional but recommended: attach the EuRoC MAV dataset as an input if you find
   a public copy on Kaggle (search "EuRoC MAV"). Cell 9 will auto-use
   `/kaggle/input/*euroc*/` if present; otherwise it falls back to wget.
3. Run all. Use **"Save Version" → "Save & Run All (Commit)"** to execute in the
   background — Kaggle will email you when it finishes and `/kaggle/working/`
   outputs persist across sessions.
4. Build tree lives in `/kaggle/temp` (wiped between sessions). Results live in
   `/kaggle/working/slam_results` (persists across session restarts).

### Pipeline
```
/content/
├── Pangolin/           # built from source (ORB-SLAM3 dependency)
├── ORB_SLAM3/          # built headless via xvfb
├── stella_vslam/       # built headless
├── dso/                # built best-effort; graceful fallback if it fails
├── euroc/              # EuRoC sequences + converted TUM-format GT
├── results/
│   ├── orbslam3/  stella/  dso/   # per-system TUM trajectories
│   └── eval/                      # evo ATE/RPE + combined JSON
└── drive/MyDrive/slam_results/    # persistent checkpoint
```

### What is compliant with the midterm report
- Three systems (DSO elevated from optional to primary) with graceful fallback.
- Six EuRoC sequences (MH_{01,03,05}, V1_{01,02,03}).
- Metrics: ATE RMSE, RPE RMSE, **tracking success rate**, **per-frame timing**.
- Default parameters for all systems; Sim(3) alignment for monocular runs.
- Median of N runs per sequence (N configurable via `QUICK_MODE`).
- Auto-classified failure mode taxonomy.
""")

# ---------------------------------------------------------------- Cell 1
md("""---
## 0. Detect platform, mount persistent storage, create directories

Auto-detects **Colab** vs **Kaggle**. On Kaggle we symlink `/content` → a
scratch dir under `/kaggle/temp` and `/content/drive/MyDrive/slam_results` →
`/kaggle/working/slam_results`, so every downstream cell's hardcoded
`/content/...` paths work identically on both platforms.
""")

code("""import os, shutil, sys

# ---- Platform detection ----
if 'KAGGLE_KERNEL_RUN_TYPE' in os.environ or os.path.isdir('/kaggle/working'):
    PLATFORM = 'kaggle'
elif 'COLAB_GPU' in os.environ or os.path.isdir('/content'):
    PLATFORM = 'colab'
else:
    PLATFORM = 'local'
print(f'Platform: {PLATFORM}')

if PLATFORM == 'colab':
    from google.colab import drive
    drive.mount('/content/drive')
    CHECKPOINT_ROOT = '/content/drive/MyDrive/slam_results'

elif PLATFORM == 'kaggle':
    # Kaggle rootfs is an overlayfs that refuses os.symlink at '/', so we
    # mkdir /content directly. Kaggle's session has ~73 GB of shared scratch
    # across '/', /kaggle/temp, and /kaggle/working — plenty for the build
    # tree + EuRoC. Checkpoints go to /kaggle/working/slam_results which
    # persists across notebook commits (the only "saved" storage on Kaggle).
    os.makedirs('/content', exist_ok=True)
    CHECKPOINT_ROOT = '/kaggle/working/slam_results'
    os.makedirs(CHECKPOINT_ROOT, exist_ok=True)
    os.makedirs('/content/drive/MyDrive', exist_ok=True)
    link = '/content/drive/MyDrive/slam_results'
    if not os.path.exists(link) and not os.path.islink(link):
        try:
            os.symlink(CHECKPOINT_ROOT, link)
        except (OSError, NotImplementedError) as e:
            # Fallback if the filesystem refuses symlinks: use a plain dir.
            # A final cell at notebook end copies this to CHECKPOINT_ROOT.
            print(f'Warning: symlink to {CHECKPOINT_ROOT} failed ({e}); using directory fallback.')
            os.makedirs(link, exist_ok=True)

else:
    raise RuntimeError(
        'Unsupported platform. Run this notebook on Google Colab or Kaggle.')

DIRS = [
    '/content/euroc',
    '/content/results/orbslam3',
    '/content/results/stella',
    '/content/results/dso',
    '/content/results/eval',
    '/content/drive/MyDrive/slam_results/orbslam3',
    '/content/drive/MyDrive/slam_results/stella',
    '/content/drive/MyDrive/slam_results/dso',
    '/content/drive/MyDrive/slam_results/eval',
]
for d in DIRS:
    os.makedirs(d, exist_ok=True)

print(f'Checkpoints: {CHECKPOINT_ROOT}')
print(f'Disk free  : {shutil.disk_usage("/content").free / 1e9:.1f} GB at /content')
""")

# ---------------------------------------------------------------- Cell 1b
md("""---
## 0b. Restore build cache (if available)

On Kaggle: `/kaggle/working/build_cache.tgz` persists across notebook commits.
On Colab: uses `drive/MyDrive/slam_build_cache.tgz`.

If the cache exists, we untar it into `/` and `/usr/local` — that restores the
entire Pangolin / ORB-SLAM3 / Stella / DSO build tree in ~30 seconds, turning
the ~30–40 min cold rebuild into a skip. If it doesn't exist, this cell is a
no-op and cells 2–8 will build from source normally. After the first
successful build, run the "snapshot build cache" cell below to populate it.
""")

code("""import os, subprocess

if PLATFORM == 'kaggle':
    BUILD_CACHE = '/kaggle/working/build_cache.tgz'
elif PLATFORM == 'colab':
    BUILD_CACHE = '/content/drive/MyDrive/slam_build_cache.tgz'
else:
    BUILD_CACHE = None

if BUILD_CACHE and os.path.isfile(BUILD_CACHE) and not os.path.isdir('/content/ORB_SLAM3'):
    sz = os.path.getsize(BUILD_CACHE) / 1e9
    print(f'Restoring build cache from {BUILD_CACHE} ({sz:.2f} GB) ...')
    subprocess.run(['tar', 'xzf', BUILD_CACHE, '-C', '/'], check=True)
    subprocess.run(['ldconfig'], check=False)
    print('Cache restored. Cells 4-8 will skip their build steps.')
elif os.path.isdir('/content/ORB_SLAM3'):
    print('Build tree already present in /content — nothing to restore.')
else:
    print(f'No build cache found at {BUILD_CACHE}.')
    print('Cells 2-8 will build from source (~30-40 min).')
    print('After that finishes, run the "snapshot build cache" cell to save it.')
""")

# ---------------------------------------------------------------- Cell 2
md("""---
## 1. Global configuration

`QUICK_MODE = True` runs each sequence **once** (for end-to-end smoke tests).
Set it to `False` for the full midterm protocol of **three runs per sequence**
with median selection.
""")

code("""# ---- Global configuration ----
QUICK_MODE = True   # True: 1 run/seq (~1h total); False: 3 runs/seq (~3-4h total)

NUM_RUNS = 1 if QUICK_MODE else 3

SEQUENCES = [
    # (name, euroc_subfolder, difficulty)
    ('MH_01_easy',       'machine_hall', 'easy'),
    ('V1_01_easy',       'vicon_room1',  'easy'),
    ('MH_03_medium',     'machine_hall', 'medium'),
    ('V1_02_medium',     'vicon_room1',  'medium'),
    ('MH_05_difficult',  'machine_hall', 'difficult'),
    ('V1_03_difficult',  'vicon_room1',  'difficult'),
]
SEQ_NAMES = [s[0] for s in SEQUENCES]

# Per-frame timing threshold below which we flag a "performance bottleneck"
# (EuRoC cam0 is 20Hz = 50ms/frame, so >50ms means real-time can't be maintained)
REALTIME_BUDGET_MS = 50.0

print(f'QUICK_MODE={QUICK_MODE}  NUM_RUNS={NUM_RUNS}  |  {len(SEQUENCES)} sequences')
""")

# ---------------------------------------------------------------- Cell 3
md("""---
## 2. Install system dependencies
Shared deps for all three SLAM systems plus `xvfb` for headless rendering.
""")

code(r"""%%bash
set -e
export DEBIAN_FRONTEND=noninteractive
LOG=/tmp/apt_install.log
: > "$LOG"

echo '=== Installing apt dependencies ==='
# Repair any broken/half-configured dpkg state from the Colab/Kaggle base image
dpkg --configure -a >> "$LOG" 2>&1 || true
apt-get install -f -y -qq >> "$LOG" 2>&1 || true

echo '  updating package lists...'
apt-get update -qq >> "$LOG" 2>&1 || { echo '--- apt-get update failed ---'; tail -40 "$LOG"; exit 1; }

# Packages whose names sometimes change between Ubuntu releases are installed
# individually with a fallback so a single missing package doesn't kill the cell.
apt_install_one() {
    for pkg in "$@"; do
        if apt-get install -y -qq "$pkg" >> "$LOG" 2>&1; then
            return 0
        fi
    done
    echo "WARNING: none of [$*] could be installed; continuing." >&2
    return 0
}

# Core toolchain (must succeed)
echo '  installing core packages (this takes 3-5 min on Kaggle)...'
apt-get install -y -qq \
    cmake gcc g++ git wget unzip pkg-config ca-certificates \
    xvfb \
    libeigen3-dev \
    libopencv-dev libopencv-contrib-dev \
    libglew-dev libwayland-dev libxkbcommon-dev \
    libepoxy-dev \
    libboost-all-dev \
    libsuitesparse-dev \
    libyaml-cpp-dev \
    libssl-dev \
    libgoogle-glog-dev libgflags-dev \
    libspdlog-dev nlohmann-json3-dev \
    libzip-dev libpng-dev \
    python3-pip \
    >> "$LOG" 2>&1 || { echo '--- apt-get install (core) failed, last 60 lines of log: ---'; tail -60 "$LOG"; exit 1; }
echo '  core packages done.'

# Packages that were renamed/split across Ubuntu versions — try each name in turn
echo '  installing optional/renamed packages...'
apt_install_one libgl-dev libgl1-mesa-dev
apt_install_one libegl-dev libegl1-mesa-dev
apt_install_one libc++-dev libc++-14-dev libc++-13-dev libc++-12-dev
apt_install_one libjpeg-dev libjpeg-turbo8-dev libjpeg62-turbo-dev

echo '=== Installing Python packages ==='
pip install -q 'evo==1.28.0' numpy matplotlib pandas tqdm

echo '--- Versions ---'
echo "CMake  : $(cmake --version | head -1)"
echo "GCC    : $(gcc --version | head -1)"
python3 -c "import cv2; print(f'OpenCV : {cv2.__version__}')" || echo 'OpenCV : (python binding not installed — C++ libs only)'
echo "Eigen  : $(pkg-config --modversion eigen3 2>/dev/null || echo '(headers at /usr/include/eigen3)')"
echo "xvfb   : $(which xvfb-run)"
echo '=== Done ==='
""")

# ---------------------------------------------------------------- Cell 4
md("""---
## 3. Build Pangolin from source

ORB-SLAM3's build hard-requires Pangolin. Ubuntu 22.04 has no apt package, so
we build v0.6 (ORB-SLAM3-compatible) from source. We keep the viewer compiled
but never create a window; instead we run the SLAM binary under `xvfb-run`.
""")

code(r"""%%bash
set -e
if [ -f /usr/local/lib/libpango_core.so ] || [ -f /usr/local/lib/libpango_core.a ]; then
    echo 'Pangolin already installed, skipping.'
    exit 0
fi

cd /content
if [ ! -d Pangolin ]; then
    git clone --depth 1 --branch v0.6 https://github.com/stevenlovegrove/Pangolin.git
fi
cd Pangolin
rm -rf build   # start clean — a half-finished prior build will re-trigger the same errors
mkdir -p build && cd build

# BUILD_TOOLS=OFF skips Pangolin's VideoViewer / VideoConvert binaries. On
# current Colab (Ubuntu 22.04), linking those fails with
#   libGL.so: undefined reference to '_glapi_tls_Current'
# because mesa's libGL doesn't carry an implicit libglapi link. ORB-SLAM3 only
# needs the Pangolin *library*, which builds and installs cleanly without the
# tools. BUILD_PANGOLIN_FFMPEG=OFF avoids another common v0.6 break on recent
# ffmpeg. -Wno-error keeps picojson.h -Wparentheses warnings from failing the
# build if -Werror is on.
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_EXAMPLES=OFF \
    -DBUILD_TESTS=OFF \
    -DBUILD_TOOLS=OFF \
    -DBUILD_PANGOLIN_PYTHON=OFF \
    -DBUILD_PANGOLIN_FFMPEG=OFF \
    -DCMAKE_CXX_FLAGS='-Wno-error -Wno-parentheses -Wno-deprecated-declarations' \
    > /tmp/pangolin_cmake.log 2>&1 || { echo '--- cmake log (last 40 lines): ---'; tail -40 /tmp/pangolin_cmake.log; exit 1; }

make -j$(nproc) > /tmp/pangolin_build.log 2>&1 || { echo '--- make log (last 60 lines): ---'; tail -60 /tmp/pangolin_build.log; exit 1; }
make install > /tmp/pangolin_install.log 2>&1 || { echo '--- install log: ---'; tail -40 /tmp/pangolin_install.log; exit 1; }
ldconfig
echo '=== Pangolin installed ==='
""")

# ---------------------------------------------------------------- Cell 5
md("""---
## 4. Build ORB-SLAM3

Builds the official repo with only two minimal patches (C++14 for modern GCC,
Eigen alignment in `LoopClosing.h`). The viewer stays compiled — we run under
`xvfb-run` so it never actually pops a window.
""")

code(r"""%%bash
set -e
cd /content

if [ -f /content/ORB_SLAM3/Examples/Monocular/mono_euroc ]; then
    echo 'ORB-SLAM3 already built, skipping.'
    exit 0
fi

echo '=== Cloning ORB-SLAM3 ==='
if [ ! -d /content/ORB_SLAM3 ]; then
    git clone --depth 1 https://github.com/UZ-SLAMLab/ORB_SLAM3.git /content/ORB_SLAM3
fi
cd /content/ORB_SLAM3

# Patch 1: C++14 (top-level + Thirdparty)
sed -i 's/set(CMAKE_CXX_STANDARD 11)/set(CMAKE_CXX_STANDARD 14)/' CMakeLists.txt
find Thirdparty -name CMakeLists.txt -exec sed -i 's/set(CMAKE_CXX_STANDARD 11)/set(CMAKE_CXX_STANDARD 14)/' {} \;

# Patch 2: Eigen alignment in LoopClosing.h (prevents segfault under newer Eigen)
if ! grep -q 'EIGEN_MAKE_ALIGNED_OPERATOR_NEW' include/LoopClosing.h; then
    python3 - <<'PYEOF'
import re, pathlib
p = pathlib.Path('include/LoopClosing.h')
src = p.read_text()
# Insert macro right after the first `public:` inside the LoopClosing class
patched = re.sub(
    r'(class LoopClosing[^{]*\{[^}]*?public:\s*)',
    r'\1\n    EIGEN_MAKE_ALIGNED_OPERATOR_NEW\n',
    src, count=1, flags=re.DOTALL)
p.write_text(patched)
print('Patched LoopClosing.h')
PYEOF
fi

# Use the build script the repo ships with; it handles Thirdparty (DBoW2, g2o, Sophus) + main
chmod +x build.sh
./build.sh 2>&1 | tail -30

if [ -f /content/ORB_SLAM3/Examples/Monocular/mono_euroc ]; then
    echo '=== ORB-SLAM3 BUILD SUCCESSFUL ==='
else
    echo '=== ORB-SLAM3 BUILD FAILED — see output above ==='
    exit 1
fi
""")

# ---------------------------------------------------------------- Cell 6
md("""---
## 5. Build Stella-VSLAM

Stella-VSLAM (community maintained fork of OpenVSLAM). Headless build with
Pangolin viewer and socket publisher both disabled.
""")

code(r"""%%bash
set -e
cd /content

# Skip if an EuRoC runner binary already exists anywhere in the build tree
if find /content/stella_vslam/build -name 'run_euroc*' -type f 2>/dev/null | grep -q .; then
    echo 'Stella-VSLAM already built, skipping.'
    exit 0
fi

if [ ! -d /content/stella_vslam ]; then
    git clone --recursive --depth 1 https://github.com/stella-cv/stella_vslam.git /content/stella_vslam
fi
cd /content/stella_vslam
git submodule update --init --recursive 2>/dev/null || true

# Stella bundles FBoW + g2o under 3rd/. Build and install each.
for sub in 3rd/FBoW 3rd/fbow 3rd/g2o; do
    if [ -d "$sub" ]; then
        echo "=== Building $sub ==="
        pushd "$sub" > /dev/null
        mkdir -p build && cd build
        cmake .. -DCMAKE_BUILD_TYPE=Release > /tmp/${sub//\//_}_cmake.log 2>&1
        make -j$(nproc) > /tmp/${sub//\//_}_build.log 2>&1
        make install > /dev/null 2>&1 || sudo make install > /dev/null 2>&1
        popd > /dev/null
    fi
done
ldconfig 2>/dev/null || true

echo '=== Building Stella-VSLAM (headless) ==='
mkdir -p build && cd build
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DUSE_PANGOLIN_VIEWER=OFF \
    -DUSE_SOCKET_PUBLISHER=OFF \
    -DUSE_STACK_TRACE_LOGGER=ON \
    -DBUILD_TESTS=OFF \
    -DBUILD_EXAMPLES=ON \
    2>&1 | tail -20

make -j$(nproc) 2>&1 | tail -15

STELLA_BIN=$(find /content/stella_vslam/build -name 'run_euroc*' -type f 2>/dev/null | head -1)
if [ -n "$STELLA_BIN" ]; then
    echo '=== STELLA-VSLAM BUILD SUCCESSFUL ==='
    echo "Binary: $STELLA_BIN"
else
    echo '=== Stella build produced no run_euroc binary ==='
    echo 'Executables in build/:'
    find /content/stella_vslam/build -type f -executable | head -20
    exit 1
fi
""")

# ---------------------------------------------------------------- Cell 7
md("""### 5b. Download Stella-VSLAM FBoW vocabulary
""")

code(r"""%%bash
set -e
VOCAB_DIR=/content/stella_vslam/vocab
mkdir -p $VOCAB_DIR
if [ -s $VOCAB_DIR/orb_vocab.fbow ]; then
    echo 'Vocab already present.'
    exit 0
fi

# Primary source: Stella's own FBoW vocab repo
wget -q -O $VOCAB_DIR/orb_vocab.fbow \
    https://github.com/stella-cv/FBoW_orb_vocab/raw/main/orb_vocab.fbow || true

if [ ! -s $VOCAB_DIR/orb_vocab.fbow ]; then
    # Fallback: release asset
    wget -q -O $VOCAB_DIR/orb_vocab.fbow \
        https://github.com/stella-cv/FBoW_orb_vocab/releases/download/v1.0/orb_vocab.fbow || true
fi

if [ -s $VOCAB_DIR/orb_vocab.fbow ]; then
    echo "Vocab downloaded: $(ls -lh $VOCAB_DIR/orb_vocab.fbow | awk '{print $5}')"
else
    echo 'WARNING: Stella vocab download failed. Stella runs will be skipped.'
    exit 0   # don't fail the whole pipeline
fi
""")

# ---------------------------------------------------------------- Cell 8
md("""---
## 6. Build DSO (best-effort)

DSO doesn't ship a EuRoC runner or photometric calibration. We build Engel's
reference implementation with a few modern-Ubuntu compatibility patches, then
later generate a `camera.txt` from each sequence's `sensor.yaml` and run with
`mode=1` (online photometric optimization — no `pcalib.txt`/`vignette` needed).

If the build fails for any reason, we annotate a failure record and the rest
of the pipeline continues without DSO.
""")

code(r"""%%bash
set -e
mkdir -p /content/dso_status

if [ -f /content/dso/build/bin/dso_dataset ]; then
    echo 'DSO already built.'
    echo 'ok' > /content/dso_status/state
    exit 0
fi

(
    cd /content
    if [ ! -d dso ]; then
        git clone --depth 1 https://github.com/JakobEngel/dso.git
    fi
    cd dso

    # ---- Patches for modern Ubuntu / GCC ----
    # Bump C++ standard (DSO default is C++11; newer GCC versions need C++14 for <limits> dependents)
    sed -i 's/-std=c++0x/-std=c++14/g; s/-std=c++11/-std=c++14/g' CMakeLists.txt || true

    # Add missing <limits> include if GCC complains (only patch files that don't already have it)
    for f in src/util/NumType.h src/util/settings.h; do
        if [ -f "$f" ] && ! grep -q '<limits>' "$f"; then
            sed -i '1i #include <limits>' "$f" 2>/dev/null || true
        fi
    done

    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release > /tmp/dso_cmake.log 2>&1 || {
        echo '--- DSO cmake failed (last 20 lines): ---'
        tail -20 /tmp/dso_cmake.log
        exit 1
    }
    make -j$(nproc) > /tmp/dso_build.log 2>&1 || {
        echo '--- DSO build failed (last 30 lines): ---'
        tail -30 /tmp/dso_build.log
        exit 1
    }
)

if [ -f /content/dso/build/bin/dso_dataset ]; then
    echo '=== DSO BUILD SUCCESSFUL ==='
    echo 'ok' > /content/dso_status/state
else
    echo '=== DSO build did not produce dso_dataset (graceful fallback engaged) ==='
    echo 'failed' > /content/dso_status/state
fi
""")

# ---------------------------------------------------------------- Cell 8b
md("""---
## 6b. Snapshot build cache (run once, then leave disabled)

After cells 2–8 have all succeeded at least once, flip `SAVE_BUILD_CACHE = True`
in the cell below and run it. It tars up Pangolin / ORB-SLAM3 / Stella / DSO
plus the `/usr/local` Pangolin install, and saves to either
`/kaggle/working/build_cache.tgz` (Kaggle) or Drive (Colab).

On subsequent sessions the "restore build cache" cell at the top will
untar this in ~30 sec, skipping the 30–40 min rebuild.

**Leave `SAVE_BUILD_CACHE = False` for normal runs** — re-tarring adds
2–3 minutes and isn't needed unless you've changed the build.
""")

code(r"""%%bash
SAVE_BUILD_CACHE=0   # set to 1 ONCE after a clean build, then back to 0

if [ "$SAVE_BUILD_CACHE" != "1" ]; then
    echo 'SAVE_BUILD_CACHE=0 — skipping snapshot.'
    exit 0
fi

# Pick destination based on whether we're on Kaggle or Colab
if [ -d /kaggle/working ]; then
    CACHE=/kaggle/working/build_cache.tgz
elif [ -d /content/drive/MyDrive ]; then
    CACHE=/content/drive/MyDrive/slam_build_cache.tgz
else
    echo 'No persistent destination found.' >&2
    exit 1
fi

mkdir -p "$(dirname "$CACHE")"
echo "Snapshotting build tree to $CACHE ..."

# -C / + relative paths avoids tar's "removing leading /" warnings.
# Excludes strip the bulky object files we don't need for runtime.
tar czf "$CACHE" \
    --exclude='*.o' --exclude='*.obj' --exclude='.git' --exclude='Thirdparty/*/build/CMakeFiles' \
    -C / \
    $(cd / && ls -d content/Pangolin content/ORB_SLAM3 content/stella_vslam content/dso content/dso_status 2>/dev/null) \
    $(cd / && ls -d usr/local/lib/libpango_*.so* usr/local/include/pangolin 2>/dev/null)

SZ=$(du -h "$CACHE" | awk '{print $1}')
echo "=== Snapshot saved: $CACHE ($SZ) ==="
""")

# ---------------------------------------------------------------- Cell 9
md("""---
## 7. Download EuRoC sequences

Downloads the six-sequence subset defined in Section V.B of the midterm:
- **Easy (baseline)**: `MH_01_easy`, `V1_01_easy`
- **Medium**: `MH_03_medium`, `V1_02_medium`
- **Difficult (severe degradation)**: `MH_05_difficult`, `V1_03_difficult`

Skips sequences already on disk.
""")

code(r"""import os, subprocess, shutil, glob

EUROC_BASE = 'http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset'
DEST       = '/content/euroc'

# ---- Kaggle: check if a EuRoC dataset is already attached as an input ----
# If a user attached a public EuRoC MAV dataset to the notebook, symlink its
# sequence folders into /content/euroc instead of re-downloading (~10 min saved).
def _try_kaggle_input():
    found = {}
    candidates = glob.glob('/kaggle/input/*/**/mav0', recursive=True)
    for mav0 in candidates:
        # Sequence name is the parent dir of mav0/
        seq_dir = os.path.dirname(mav0)
        seq_name = os.path.basename(seq_dir)
        found[seq_name] = seq_dir
    return found

kaggle_map = _try_kaggle_input() if os.path.isdir('/kaggle/input') else {}
if kaggle_map:
    print(f'[KAGGLE] Found {len(kaggle_map)} EuRoC sequences in /kaggle/input — using those.')

for seq_name, subfolder, _ in SEQUENCES:
    target = f'{DEST}/{seq_name}'
    if os.path.isdir(f'{target}/mav0'):
        print(f'[SKIP] {seq_name} already downloaded')
        continue

    # Kaggle fast path: symlink the attached dataset's sequence folder
    if seq_name in kaggle_map:
        os.makedirs(target, exist_ok=True)
        link = f'{target}/mav0'
        if not os.path.exists(link):
            os.symlink(f'{kaggle_map[seq_name]}/mav0', link)
        print(f'[LINK] {seq_name} -> {kaggle_map[seq_name]}')
        continue

    url = f'{EUROC_BASE}/{subfolder}/{seq_name}/{seq_name}.zip'
    zip_path = f'/tmp/{seq_name}.zip'
    print(f'[DOWNLOAD] {seq_name} ... ', end='', flush=True)
    subprocess.run(['wget', '-q', '-O', zip_path, url], check=True)
    os.makedirs(target, exist_ok=True)
    subprocess.run(['unzip', '-q', '-o', zip_path, '-d', target], check=True)
    os.remove(zip_path)
    print('done')

# Summary
total = 0
for seq_name, _, _ in SEQUENCES:
    size = shutil.disk_usage(f'{DEST}/{seq_name}').used if os.path.isdir(f'{DEST}/{seq_name}') else 0
    du = subprocess.run(['du', '-sh', f'{DEST}/{seq_name}'], capture_output=True, text=True).stdout.split()[0]
    print(f'  {seq_name}: {du}')
""")

# ---------------------------------------------------------------- Cell 10
md("""---
## 8. Prepare ground truth + frame counts

- Converts each sequence's EuRoC GT CSV → TUM format (`gt.tum`) so the SLAM
  outputs (also TUM) can be compared with `evo_ape tum` directly.
- Counts input frames in `cam0/data/` per sequence — needed later for the
  **tracking success rate** metric (rows_in_trajectory / input_frames).
""")

code(r"""import os, glob
import pandas as pd

EUROC = '/content/euroc'
frame_counts = {}

for seq_name, _, _ in SEQUENCES:
    base = f'{EUROC}/{seq_name}/mav0'
    if not os.path.isdir(base):
        print(f'[SKIP] {seq_name} — not downloaded')
        continue

    # ---- Convert GT CSV to TUM ----
    gt_csv = f'{base}/state_groundtruth_estimate0/data.csv'
    gt_tum = f'{EUROC}/{seq_name}/gt.tum'
    if os.path.isfile(gt_csv) and not os.path.isfile(gt_tum):
        # EuRoC CSV columns: ts, px, py, pz, qw, qx, qy, qz, vx, vy, vz, wx, wy, wz, ax, ay, az
        # comment='#' drops the header line; header=None prevents pandas from promoting a data row.
        df = pd.read_csv(gt_csv, comment='#', header=None)
        ts_s = df.iloc[:, 0].astype('int64') / 1e9
        # TUM columns: ts x y z qx qy qz qw  (quaternion order differs from EuRoC!)
        out = pd.DataFrame({
            'ts': ts_s,
            'x':  df.iloc[:, 1],
            'y':  df.iloc[:, 2],
            'z':  df.iloc[:, 3],
            'qx': df.iloc[:, 5],
            'qy': df.iloc[:, 6],
            'qz': df.iloc[:, 7],
            'qw': df.iloc[:, 4],
        })
        out.to_csv(gt_tum, sep=' ', header=False, index=False,
                   float_format='%.9f')
        print(f'[GT]    {seq_name}: wrote {gt_tum} ({len(out)} rows)')
    elif os.path.isfile(gt_tum):
        print(f'[GT]    {seq_name}: already converted')

    # ---- Count input frames ----
    imgs = glob.glob(f'{base}/cam0/data/*.png')
    frame_counts[seq_name] = len(imgs)
    print(f'[FRAMES] {seq_name}: {len(imgs)} cam0 images')

# Stash for later cells
import json
with open('/content/results/frame_counts.json', 'w') as f:
    json.dump(frame_counts, f, indent=2)
""")

# ---------------------------------------------------------------- Cell 11
md("""---
## 9. Helpers: trajectory I/O, evaluation, failure classification

All downstream cells use these utilities so each system's run loop stays short.
""")

code(r"""import os, json, subprocess, time, shutil, glob, zipfile
from pathlib import Path

EVO_ZIP_STATS_KEY = 'stats'   # evo --save_results writes stats.json inside the zip

def count_traj_rows(path):
    '''Count non-comment rows in a TUM trajectory file.'''
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return 0
    n = 0
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#'):
                n += 1
    return n


def run_evo(metric, gt_tum, est_tum, out_zip, sim3=True):
    '''Run evo_ape or evo_rpe in TUM mode and return RMSE (float or None).'''
    assert metric in ('ape', 'rpe')
    binary = f'evo_{metric}'
    cmd = [binary, 'tum', gt_tum, est_tum, '--align']
    if sim3:
        cmd.append('--correct_scale')
    cmd += ['--save_results', out_zip, '--no_warnings']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if not os.path.isfile(out_zip):
        return None
    # Pull rmse out of the stats.json bundled in the zip
    try:
        with zipfile.ZipFile(out_zip) as zf:
            with zf.open('stats.json') as sf:
                stats = json.load(sf)
        return float(stats.get('rmse'))
    except Exception:
        return None


def classify_failure(ate, rpe, success_rate, per_frame_ms):
    '''Rule-based failure taxonomy (matches midterm report IV.D).

    Returns one of:
        success, minor_drift, tracking_divergence, tracking_loss,
        feature_starvation, performance_bottleneck, complete_failure
    Rules are applied in order; first match wins.
    '''
    if ate is None or success_rate is None or success_rate == 0:
        return 'complete_failure'
    if success_rate < 0.30:
        return 'feature_starvation'
    if success_rate < 0.85:
        return 'tracking_loss'
    if per_frame_ms is not None and per_frame_ms > REALTIME_BUDGET_MS:
        return 'performance_bottleneck'
    if ate > 1.0:
        return 'tracking_divergence'
    if ate > 0.3:
        return 'minor_drift'
    return 'success'


def checkpoint_dir(src_dir, dst_dir, prefix=None):
    '''Copy files from src_dir to dst_dir (Drive). Optionally filter by prefix.'''
    os.makedirs(dst_dir, exist_ok=True)
    for f in os.listdir(src_dir):
        if prefix and not f.startswith(prefix):
            continue
        shutil.copy2(f'{src_dir}/{f}', f'{dst_dir}/{f}')


print('Helpers loaded.')
""")

# ---------------------------------------------------------------- Cell 12
md("""---
## 10. Run ORB-SLAM3

Monocular ORB-SLAM3 on each sequence, `NUM_RUNS` times. Launched under
`xvfb-run` so the compiled-in Pangolin viewer has a virtual display to attach
to but never renders anything visible.
""")

code(r"""import subprocess, os, time, shutil, json

ORB = '/content/ORB_SLAM3'
VOCAB    = f'{ORB}/Vocabulary/ORBvoc.txt'
CONFIG   = f'{ORB}/Examples/Monocular/EuRoC.yaml'
BINARY   = f'{ORB}/Examples/Monocular/mono_euroc'
TS_DIR   = f'{ORB}/Examples/Monocular/EuRoC_TimeStamps'

TIMESTAMP_MAP = {
    'MH_01_easy':       'MH01.txt',
    'V1_01_easy':       'V101.txt',
    'MH_03_medium':     'MH03.txt',
    'V1_02_medium':     'V102.txt',
    'MH_05_difficult':  'MH05.txt',
    'V1_03_difficult':  'V103.txt',
}

RESULTS = '/content/results/orbslam3'
DRIVE   = '/content/drive/MyDrive/slam_results/orbslam3'

if not os.path.isfile(BINARY):
    print('ERROR: mono_euroc binary missing — did the ORB-SLAM3 build succeed?')
else:
    run_log = {}

    for seq, _, _ in SEQUENCES:
        seq_dir = f'/content/euroc/{seq}'
        if not os.path.isdir(f'{seq_dir}/mav0'):
            print(f'[SKIP] {seq}')
            continue

        ts_file = f'{TS_DIR}/{TIMESTAMP_MAP[seq]}'
        run_log[seq] = []
        print(f'\n{"="*60}\nORB-SLAM3 on {seq} ({NUM_RUNS} runs)')

        for i in range(NUM_RUNS):
            out = f'{RESULTS}/{seq}_run{i}.txt'
            # Purge stale outputs from a prior run so we never copy them forward on failure
            for stale in (f'{ORB}/CameraTrajectory.txt', f'{ORB}/KeyFrameTrajectory.txt'):
                if os.path.isfile(stale):
                    os.remove(stale)
            print(f'  run {i+1}/{NUM_RUNS} ...', end=' ', flush=True)
            t0 = time.time()
            try:
                # mono_euroc expects the sequence PARENT of mav0 (it appends /mav0/cam0/data internally)
                cmd = ['xvfb-run', '-a', '-s', '-screen 0 640x480x24',
                       BINARY, VOCAB, CONFIG, seq_dir, ts_file]
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=900, cwd=ORB)
                elapsed = time.time() - t0

                traj_found = False
                for cand in (f'{ORB}/CameraTrajectory.txt', f'{ORB}/KeyFrameTrajectory.txt'):
                    if os.path.isfile(cand) and os.path.getsize(cand) > 0:
                        shutil.copy2(cand, out)
                        traj_found = True
                        break
                success = traj_found and r.returncode == 0
                n_rows = count_traj_rows(out) if success else 0
                print(f'{"OK" if success else "FAIL"}  t={elapsed:.1f}s  rows={n_rows}')
                if not success:
                    for line in r.stderr.strip().splitlines()[-3:]:
                        print(f'    {line}')

                run_log[seq].append({
                    'run': i,
                    'time_s': round(elapsed, 2),
                    'output': out if success else None,
                    'success': success,
                    'traj_rows': n_rows,
                })
            except subprocess.TimeoutExpired:
                elapsed = time.time() - t0
                print(f'TIMEOUT  t={elapsed:.1f}s')
                run_log[seq].append({'run': i, 'time_s': round(elapsed, 2),
                                     'output': None, 'success': False, 'traj_rows': 0})

        checkpoint_dir(RESULTS, DRIVE, prefix=seq)

    with open(f'{RESULTS}/run_log.json', 'w') as f:
        json.dump(run_log, f, indent=2)
    shutil.copy2(f'{RESULTS}/run_log.json', f'{DRIVE}/run_log.json')
    print('\n=== ORB-SLAM3 runs complete ===')
""")

# ---------------------------------------------------------------- Cell 13
md("""---
## 11. Run Stella-VSLAM
""")

code(r"""import subprocess, os, time, shutil, json, glob

STELLA  = '/content/stella_vslam'
VOCAB   = f'{STELLA}/vocab/orb_vocab.fbow'
RESULTS = '/content/results/stella'
DRIVE   = '/content/drive/MyDrive/slam_results/stella'

# Find the run_euroc binary (location varies between stella versions)
STELLA_BIN = next(iter(sorted(glob.glob(f'{STELLA}/build/**/run_euroc*', recursive=True))), None)

# Locate a monocular EuRoC config YAML shipped with Stella
STELLA_CONFIG = None
for pat in ('example/**/euroc_mono.yaml', 'example/**/EuRoC_mono.yaml',
            '**/euroc*mono*.yaml', 'example/**/euroc.yaml'):
    hit = sorted(glob.glob(f'{STELLA}/{pat}', recursive=True))
    if hit:
        STELLA_CONFIG = hit[0]
        break

print(f'Stella binary: {STELLA_BIN}')
print(f'Stella config: {STELLA_CONFIG}')
print(f'Stella vocab : {VOCAB}')

if not STELLA_BIN or not STELLA_CONFIG or not os.path.isfile(VOCAB):
    print('\nSkipping Stella runs (binary, config, or vocab missing).')
else:
    run_log = {}
    for seq, _, _ in SEQUENCES:
        seq_dir = f'/content/euroc/{seq}'
        data_path = f'{seq_dir}/mav0' if os.path.isdir(f'{seq_dir}/mav0') else seq_dir
        if not os.path.isdir(data_path):
            print(f'[SKIP] {seq}')
            continue

        run_log[seq] = []
        print(f'\n{"="*60}\nStella-VSLAM on {seq} ({NUM_RUNS} runs)')

        for i in range(NUM_RUNS):
            out = f'{RESULTS}/{seq}_run{i}.txt'
            # Stella writes frame_trajectory.txt under --eval-log-dir. Purge stale copies.
            stella_traj = '/tmp/frame_trajectory.txt'
            for stale in (stella_traj, '/tmp/keyframe_trajectory.txt'):
                if os.path.isfile(stale):
                    os.remove(stale)
            print(f'  run {i+1}/{NUM_RUNS} ...', end=' ', flush=True)

            cmd = ['xvfb-run', '-a', '-s', '-screen 0 640x480x24',
                   STELLA_BIN,
                   '-v', VOCAB,
                   '-d', data_path,
                   '-c', STELLA_CONFIG,
                   '--auto-term',
                   '--no-sleep',
                   '--eval-log-dir', '/tmp',
                   '--map-db-out',  f'/tmp/stella_{seq}_{i}.msg']

            t0 = time.time()
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
                elapsed = time.time() - t0

                if os.path.isfile(stella_traj) and os.path.getsize(stella_traj) > 0:
                    shutil.copy2(stella_traj, out)
                    success = True
                else:
                    success = False
                n_rows = count_traj_rows(out) if success else 0
                print(f'{"OK" if success else "FAIL"}  t={elapsed:.1f}s  rows={n_rows}')
                if not success:
                    for line in r.stderr.strip().splitlines()[-3:]:
                        print(f'    {line}')

                run_log[seq].append({
                    'run': i,
                    'time_s': round(elapsed, 2),
                    'output': out if success else None,
                    'success': success,
                    'traj_rows': n_rows,
                })
            except subprocess.TimeoutExpired:
                elapsed = time.time() - t0
                print(f'TIMEOUT  t={elapsed:.1f}s')
                run_log[seq].append({'run': i, 'time_s': round(elapsed, 2),
                                     'output': None, 'success': False, 'traj_rows': 0})

        checkpoint_dir(RESULTS, DRIVE, prefix=seq)

    with open(f'{RESULTS}/run_log.json', 'w') as f:
        json.dump(run_log, f, indent=2)
    shutil.copy2(f'{RESULTS}/run_log.json', f'{DRIVE}/run_log.json')
    print('\n=== Stella-VSLAM runs complete ===')
""")

# ---------------------------------------------------------------- Cell 14
md("""---
## 12. Run DSO (best-effort)

DSO reads an image folder plus a text-format `camera.txt` (intrinsics +
distortion). We synthesise one per sequence from EuRoC's `sensor.yaml`, then
run DSO with `mode=1` (online photometric optimization — no `pcalib.txt`/
`vignette.png` required). If the DSO binary is absent, we skip and log the
state; downstream cells treat DSO results as missing.
""")

code(r"""import os, yaml, subprocess, time, shutil, json, glob

DSO_BIN = '/content/dso/build/bin/dso_dataset'
RESULTS = '/content/results/dso'
DRIVE   = '/content/drive/MyDrive/slam_results/dso'

dso_state = '/content/dso_status/state'
dso_ok = os.path.isfile(DSO_BIN) and os.path.isfile(dso_state) and open(dso_state).read().strip() == 'ok'

if not dso_ok:
    print('DSO binary not available — skipping all DSO runs (graceful fallback).')
    # Write an empty run log so the eval/classify cells still see DSO as a known system
    with open(f'{RESULTS}/run_log.json', 'w') as f:
        json.dump({'__status__': 'build_failed'}, f, indent=2)
else:
    # ---- Build per-sequence camera.txt + times.txt from sensor.yaml ----
    def write_dso_calib(seq):
        sensor = f'/content/euroc/{seq}/mav0/cam0/sensor.yaml'
        if not os.path.isfile(sensor):
            return None, None
        with open(sensor) as f:
            cfg = yaml.safe_load(f)

        # Intrinsics: [fx, fy, cx, cy]
        fx, fy, cx, cy = cfg['intrinsics']
        # Distortion: EuRoC uses radial-tangential (k1, k2, r1, r2)
        k1, k2, p1, p2 = cfg['distortion_coefficients']
        W, H = cfg['resolution']

        out_dir = f'/content/dso_input/{seq}'
        os.makedirs(out_dir, exist_ok=True)
        cam_txt = f'{out_dir}/camera.txt'
        # DSO "RadTan" calibration format (4 intrinsics + 4 distortion, normalized to image size)
        with open(cam_txt, 'w') as f:
            f.write(f'RadTan {fx/W} {fy/H} {cx/W} {cy/H} {k1} {k2} {p1} {p2}\n')
            f.write(f'{W} {H}\n')
            f.write('crop\n')
            f.write(f'{W} {H}\n')

        # DSO needs a symlinked images/ folder + times.txt listing "id timestamp exposure"
        img_src = f'/content/euroc/{seq}/mav0/cam0/data'
        img_link = f'{out_dir}/images'
        if not os.path.exists(img_link):
            os.symlink(img_src, img_link)

        # Build times.txt from the image filenames (EuRoC filenames are timestamp-in-ns)
        times_txt = f'{out_dir}/times.txt'
        if not os.path.isfile(times_txt):
            pngs = sorted(glob.glob(f'{img_src}/*.png'))
            with open(times_txt, 'w') as f:
                for p in pngs:
                    stem = os.path.splitext(os.path.basename(p))[0]
                    ts_s = int(stem) / 1e9
                    # exposure unknown -> 0 (DSO will run with mode=1)
                    f.write(f'{stem} {ts_s:.9f} 0\n')
        return out_dir, cam_txt

    run_log = {}
    for seq, _, _ in SEQUENCES:
        in_dir, cam_txt = write_dso_calib(seq)
        if in_dir is None:
            print(f'[SKIP] {seq} — no sensor.yaml')
            continue

        run_log[seq] = []
        print(f'\n{"="*60}\nDSO on {seq} ({NUM_RUNS} runs)')

        for i in range(NUM_RUNS):
            out = f'{RESULTS}/{seq}_run{i}.txt'
            # DSO writes result.txt in cwd; run each attempt in a clean folder
            cwd = f'/tmp/dso_cwd_{seq}_{i}'
            os.makedirs(cwd, exist_ok=True)
            for stale in glob.glob(f'{cwd}/*'):
                os.remove(stale)

            cmd = ['xvfb-run', '-a', '-s', '-screen 0 640x480x24',
                   DSO_BIN,
                   f'files={in_dir}/images',
                   f'calib={cam_txt}',
                   'preset=0',
                   'mode=1',         # online photometric optimization
                   'nogui=1',
                   'quiet=1']

            print(f'  run {i+1}/{NUM_RUNS} ...', end=' ', flush=True)
            t0 = time.time()
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, cwd=cwd)
                elapsed = time.time() - t0
                traj = f'{cwd}/result.txt'
                if os.path.isfile(traj) and os.path.getsize(traj) > 0:
                    shutil.copy2(traj, out)
                    success = True
                else:
                    success = False
                n_rows = count_traj_rows(out) if success else 0
                print(f'{"OK" if success else "FAIL"}  t={elapsed:.1f}s  rows={n_rows}')
                if not success:
                    for line in (r.stderr or r.stdout).strip().splitlines()[-3:]:
                        print(f'    {line}')

                run_log[seq].append({
                    'run': i,
                    'time_s': round(elapsed, 2),
                    'output': out if success else None,
                    'success': success,
                    'traj_rows': n_rows,
                })
            except subprocess.TimeoutExpired:
                elapsed = time.time() - t0
                print(f'TIMEOUT  t={elapsed:.1f}s')
                run_log[seq].append({'run': i, 'time_s': round(elapsed, 2),
                                     'output': None, 'success': False, 'traj_rows': 0})

        checkpoint_dir(RESULTS, DRIVE, prefix=seq)

    with open(f'{RESULTS}/run_log.json', 'w') as f:
        json.dump(run_log, f, indent=2)
    shutil.copy2(f'{RESULTS}/run_log.json', f'{DRIVE}/run_log.json')
    print('\n=== DSO runs complete ===')
""")

# ---------------------------------------------------------------- Cell 15
md("""---
## 13. Evaluate all trajectories with `evo`

For every (system × sequence × run) triple we compute:

- **ATE RMSE** via `evo_ape tum --align --correct_scale` (Sim(3) alignment).
- **RPE RMSE** via `evo_rpe tum --align --correct_scale`.
- **Tracking success rate** = `rows_in_trajectory / cam0_frames`.
- **Per-frame processing time** = `wall_time / cam0_frames`.

We then select the **median run** (by ATE RMSE) for each sequence.
""")

code(r"""import os, json, glob, shutil, zipfile
import numpy as np

EUROC = '/content/euroc'
EVAL_DIR  = '/content/results/eval'
DRIVE_EV  = '/content/drive/MyDrive/slam_results/eval'

with open('/content/results/frame_counts.json') as f:
    FRAME_COUNTS = json.load(f)

SYSTEMS = {
    'orbslam3': '/content/results/orbslam3',
    'stella':   '/content/results/stella',
    'dso':      '/content/results/dso',
}

def load_run_log(sys_dir):
    p = f'{sys_dir}/run_log.json'
    if os.path.isfile(p):
        try:
            return json.load(open(p))
        except Exception:
            return {}
    return {}

all_results = {}   # system -> seq -> {metrics..., all_runs: [...]}

for sys_name, sys_dir in SYSTEMS.items():
    log = load_run_log(sys_dir)
    all_results[sys_name] = {}
    print(f'\n{"="*60}\nEvaluating: {sys_name}')

    if log.get('__status__') == 'build_failed':
        print(f'  (skipped — {sys_name} build failed)')
        continue

    for seq, _, _ in SEQUENCES:
        gt_tum = f'{EUROC}/{seq}/gt.tum'
        if not os.path.isfile(gt_tum):
            print(f'  [SKIP] {seq} — no ground truth')
            continue

        run_files = sorted(glob.glob(f'{sys_dir}/{seq}_run*.txt'))
        if not run_files:
            print(f'  [SKIP] {seq} — no trajectory files')
            continue

        input_frames = FRAME_COUNTS.get(seq, 0)
        seq_runs = log.get(seq, [])

        per_run = []   # list of dicts with metrics
        for rf in run_files:
            # Look up matching run record (for wall-time -> per-frame timing)
            run_idx = int(os.path.splitext(os.path.basename(rf))[0].split('_run')[-1])
            run_meta = next((r for r in seq_runs if r.get('run') == run_idx), {})

            ate = run_evo('ape', gt_tum, rf, f'/tmp/evo_{sys_name}_{seq}_r{run_idx}_ape.zip')
            rpe = run_evo('rpe', gt_tum, rf, f'/tmp/evo_{sys_name}_{seq}_r{run_idx}_rpe.zip')
            n_rows = count_traj_rows(rf)
            success_rate = (n_rows / input_frames) if input_frames else None
            wall_s = run_meta.get('time_s')
            per_frame_ms = (wall_s * 1000.0 / input_frames) if (wall_s and input_frames) else None

            per_run.append({
                'run_idx': run_idx,
                'ate_rmse': ate,
                'rpe_rmse': rpe,
                'success_rate': success_rate,
                'per_frame_ms': per_frame_ms,
                'traj_rows': n_rows,
                'wall_s': wall_s,
                'file': rf,
            })

        # Drop runs with no ATE (completely failed evo)
        usable = [r for r in per_run if r['ate_rmse'] is not None]
        if not usable:
            # Still record the failure
            all_results[sys_name][seq] = {
                'ate_rmse': None, 'rpe_rmse': None,
                'success_rate': 0.0, 'per_frame_ms': None,
                'num_runs_total': len(per_run), 'num_runs_usable': 0,
                'all_runs': per_run,
            }
            print(f'  {seq}: all runs failed evaluation')
            continue

        # Median by ATE
        usable.sort(key=lambda r: r['ate_rmse'])
        med = usable[len(usable) // 2]
        # Persist the median run's evo zips with stable names
        shutil.copy2(f"/tmp/evo_{sys_name}_{seq}_r{med['run_idx']}_ape.zip",
                     f'{EVAL_DIR}/{sys_name}_{seq}_ate.zip')
        shutil.copy2(f"/tmp/evo_{sys_name}_{seq}_r{med['run_idx']}_rpe.zip",
                     f'{EVAL_DIR}/{sys_name}_{seq}_rpe.zip')

        all_results[sys_name][seq] = {
            'ate_rmse':     med['ate_rmse'],
            'rpe_rmse':     med['rpe_rmse'],
            'success_rate': med['success_rate'],
            'per_frame_ms': med['per_frame_ms'],
            'num_runs_total': len(per_run),
            'num_runs_usable': len(usable),
            'median_run_idx': med['run_idx'],
            'all_runs':      per_run,
        }
        print(f"  {seq}: ATE={med['ate_rmse']:.4f}  RPE={med['rpe_rmse']:.4f}  "
              f"success={med['success_rate']:.2%}  per_frame={med['per_frame_ms']:.1f}ms  "
              f"({len(usable)}/{len(per_run)} usable)")

out_path = f'{EVAL_DIR}/all_results.json'
with open(out_path, 'w') as f:
    json.dump(all_results, f, indent=2)
shutil.copy2(out_path, f'{DRIVE_EV}/all_results.json')
print(f'\n=== Wrote {out_path} ===')
""")

# ---------------------------------------------------------------- Cell 16
md("""---
## 14. Auto-classify failure modes

Applies the rule-based classifier from §IV.D of the midterm report to the
median run of each (system, sequence) pair.
""")

code(r"""import json, shutil

with open('/content/results/eval/all_results.json') as f:
    results = json.load(f)

taxonomy = {}
for sys_name, seq_map in results.items():
    taxonomy[sys_name] = {}
    for seq, m in seq_map.items():
        label = classify_failure(m.get('ate_rmse'), m.get('rpe_rmse'),
                                 m.get('success_rate'), m.get('per_frame_ms'))
        taxonomy[sys_name][seq] = label

out = '/content/results/eval/failure_taxonomy.json'
with open(out, 'w') as f:
    json.dump(taxonomy, f, indent=2)
shutil.copy2(out, '/content/drive/MyDrive/slam_results/eval/failure_taxonomy.json')

# Pretty print
print(f'\n{"Sequence":<20} ' + '  '.join(f'{s:>22}' for s in results))
for seq, _, _ in SEQUENCES:
    row = [f'{seq:<20}']
    for sys_name in results:
        label = taxonomy.get(sys_name, {}).get(seq, '—')
        row.append(f'{label:>22}')
    print('  '.join(row))

print('\nRule summary (applied in order, first match wins):')
print('  success_rate = 0 or ATE = None   -> complete_failure')
print('  success_rate < 0.30              -> feature_starvation')
print('  success_rate < 0.85              -> tracking_loss')
print(f'  per_frame_ms > {REALTIME_BUDGET_MS:.0f}ms         -> performance_bottleneck')
print('  ATE > 1.0 m                       -> tracking_divergence')
print('  ATE > 0.3 m                       -> minor_drift')
print('  else                              -> success')
""")

# ---------------------------------------------------------------- Cell 17
md("""---
## 15. Results summary: table + plots
""")

code(r"""import json, shutil
import matplotlib.pyplot as plt
import numpy as np

with open('/content/results/eval/all_results.json') as f:
    results = json.load(f)
with open('/content/results/eval/failure_taxonomy.json') as f:
    taxonomy = json.load(f)

systems = list(results.keys())
seq_names = [s[0] for s in SEQUENCES]

def fmt(v, prec=4):
    return f'{v:.{prec}f}' if isinstance(v, (int, float)) else '—'

# ---- Print table ----
print(f'{"Sequence":<20} ' + ''.join(f'{s:>14} ATE{s:>10} RPE{s:>6} SR{s:>8} ms/f ' for s in systems))
print('-' * (20 + 42 * len(systems)))
for seq in seq_names:
    row = [f'{seq:<20}']
    for sys_name in systems:
        m = results.get(sys_name, {}).get(seq, {})
        ate = fmt(m.get('ate_rmse'))
        rpe = fmt(m.get('rpe_rmse'))
        sr  = f"{m['success_rate']:.2f}" if m.get('success_rate') is not None else '—'
        pt  = fmt(m.get('per_frame_ms'), prec=1)
        row.append(f'{ate:>14} {rpe:>14} {sr:>9} {pt:>8}')
    print('  '.join(row))

print('\nFailure taxonomy:')
for seq in seq_names:
    row = [f'  {seq:<20}']
    for sys_name in systems:
        row.append(f'{sys_name}={taxonomy.get(sys_name, {}).get(seq, "—"):<22}')
    print('  '.join(row))

# ---- Plots ----
fig, axes = plt.subplots(2, 2, figsize=(14, 9))
colors = {'orbslam3': '#2196F3', 'stella': '#FF9800', 'dso': '#4CAF50'}

for ax, metric, label in [
    (axes[0, 0], 'ate_rmse',     'ATE RMSE (m)'),
    (axes[0, 1], 'rpe_rmse',     'RPE RMSE (m)'),
    (axes[1, 0], 'success_rate', 'Tracking success rate'),
    (axes[1, 1], 'per_frame_ms', 'Per-frame time (ms)'),
]:
    x = np.arange(len(seq_names))
    width = 0.8 / max(len(systems), 1)
    for i, sys_name in enumerate(systems):
        vals = [results.get(sys_name, {}).get(s, {}).get(metric) or 0 for s in seq_names]
        ax.bar(x + i * width - 0.4 + width / 2, vals, width,
               label=sys_name, color=colors.get(sys_name, None))
    ax.set_title(label)
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace('_', '\n') for s in seq_names], fontsize=8)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

axes[1, 1].axhline(REALTIME_BUDGET_MS, color='red', ls='--', lw=1, alpha=0.6,
                   label='realtime budget')
axes[1, 1].legend()

plt.tight_layout()
fig_path = '/content/results/eval/comparison_plot.png'
plt.savefig(fig_path, dpi=150)
plt.show()
shutil.copy2(fig_path, '/content/drive/MyDrive/slam_results/eval/comparison_plot.png')
print(f'\nPlot saved to {fig_path}')
""")

# ---------------------------------------------------------------- Cell 18
md("""---
## 16. Record compute environment
""")

code(r"""%%bash
echo '=== Compute Environment ==='
echo "CPU    : $(lscpu | grep 'Model name' | sed 's/.*: *//')"
echo "Cores  : $(nproc)"
echo "RAM    : $(free -h | awk '/^Mem:/{print $2}')"
echo "GPU    : $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'None')"
echo "Disk   : $(df -h /content | awk 'NR==2{print $4}') free"
echo "Ubuntu : $(lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY | cut -d= -f2)"
echo "Date   : $(date -u)"
""")

# ---------------------------------------------------------------- Cell 19
md("""---
## Notes & edge cases

### Session timeout recovery
If Colab disconnects mid-run:
1. Re-run cells 0–1 (mount Drive, set config).
2. Cells 2–8 are idempotent — they skip if binaries / vocabulary / dataset are present.
3. Cells 10–12 produce per-run TUM files that are checkpointed to Drive after
   each sequence, so you never lose results for sequences that already ran.

### Known issues & design notes
- **ORB-SLAM3 on `V1_03_difficult`**: tracking loss is expected; the partial
  trajectory is still evaluated and will typically fall into the
  `feature_starvation` or `tracking_loss` bucket in the taxonomy.
- **DSO graceful fallback**: if `cell 8` fails to produce `dso_dataset`, the
  DSO run cell writes a `__status__: build_failed` marker and the eval stage
  treats DSO results as missing instead of crashing the pipeline.
- **Sim(3) alignment**: monocular SLAM has unobservable scale, so every ATE /
  RPE call uses `--align --correct_scale`. Without this, ATE values would be
  meaninglessly large.
- **DSO without photometric calibration**: we run DSO with `mode=1` (online
  photometric param estimation). Accuracy would improve with a proper
  `pcalib.txt`/`vignette.png`, but those files aren't available for EuRoC and
  generating them is out of scope for this project.
- **Failure taxonomy heuristics**: purely rule-based on the median-run metrics.
  Cross-checking a few cases against trajectory plots is recommended before
  citing a particular label in the final report.

### Switching to the full protocol
The default `QUICK_MODE = True` runs each sequence once for fast end-to-end
validation. For the midterm's protocol (median of 3 runs), set
`QUICK_MODE = False` in cell 2 and re-run cells 10–15.
""")

# ---------------------------------------------------------------- Emit notebook
notebook = {
    "cells": cells,
    "metadata": {
        "colab": {"provenance": []},
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

with OUT.open('w', encoding='utf-8', newline='\n') as f:
    json.dump(notebook, f, indent=1, ensure_ascii=False)
    f.write('\n')

print(f'Wrote {OUT}  ({OUT.stat().st_size:,} bytes, {len(cells)} cells)')
