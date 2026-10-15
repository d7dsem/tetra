#!/usr/bin/env bash

set -euo pipefail

# Avail targets: dmo_rx (planned)

mode="release"               # debug | release
target=""                    # optional: one cmake target name
generator="${GEN:-}"         # use sys default
# OR this vay
# generator="${GEN:-Ninja}"    # use Ninja or env var GEN 
# if need other call like: 
#   GEN="Unix Makefiles" ./build.sh -m debug

# Hardcode compiler, select manualy
# compiler=gcc
compiler=clang


usage() {
  echo "Usage: $0 -m debug|release [-t target-name]"
  echo "  -m  build mode (debug|release)"
  echo "  -t  build only one target (cmake --build --target <name>)"
}

while getopts ":m:t:h" opt; do
  case "$opt" in
    m) mode="$OPTARG" ;;
    t) target="$OPTARG" ;;
    h) usage; exit 0 ;;
    \?) echo "[ERROR] Unknown option: -$OPTARG"; usage; exit 2 ;;
    :)  echo "[ERROR] Missing argument for -$OPTARG"; usage; exit 2 ;;
  esac
done
shift $((OPTIND-1))

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"


case "$mode" in
  debug)
    build_dir="$root/build-debug-$compiler"
    cfg="Debug"
    deploy_dir="$root/wd"
    ;;
  release)
    build_dir="$root/build-release-$compiler"
    cfg="Release"
    deploy_dir="$root/bin"
    ;;
  *)
    echo "[ERROR] Invalid mode: $mode"
    usage
    exit 2
    ;;
esac



# Configure (single-config)
args=( -S "$root" -B "$build_dir" "-DCMAKE_BUILD_TYPE=$cfg" "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON" )
if [[ -n "$generator" ]]; then
  args+=( -G "$generator" )
fi
# Set compiler based on selection
case "$compiler" in
  gcc)
    args+=( "-DCMAKE_C_COMPILER=gcc" "-DCMAKE_CXX_COMPILER=g++" )
    ;;
  clang)
    args+=( "-DCMAKE_C_COMPILER=clang" "-DCMAKE_CXX_COMPILER=clang++" )
    ;;
  *)
    echo "[ERROR] Unknown compiler: $compiler"
    exit 2
    ;;
esac
cmake "${args[@]}"

# Build
if [[ -n "$target" ]]; then
  cmake --build "$build_dir" --target "$target" -j
else
  cmake --build "$build_dir" -j
fi

# Update compile_commands.json symlink in repo root for clangd
if [[ -f "$build_dir/compile_commands.json" ]]; then
  ln -sf "$build_dir/compile_commands.json" "$root/compile_commands.json"
fi

# Deploy binaries from your configured output dirs: build-*/bin/<CONFIG>/*
src_bin="$build_dir/bin/$cfg"
if [[ ! -d "$src_bin" ]]; then
  echo "[ERROR] Expected binaries dir not found: $src_bin"
  exit 3
fi

mkdir -p "$deploy_dir"
if [[ -z "$target" ]]; then
  # No --delete / rm: bin/ is tracked in git and holds hand-written scripts.
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$src_bin/" "$deploy_dir/"
  else
    cp -a "$src_bin/." "$deploy_dir/"
  fi
else
  # deploy only one target (non-destructive)
  shopt -s nullglob
  matches=( "$src_bin/$target" "$src_bin/$target.exe" "$src_bin/$target"* )
  shopt -u nullglob
  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "[ERROR] Built target '$target' but no matching artifact found in: $src_bin"
    exit 4
  fi
  for f in "${matches[@]}"; do
    if [[ -f "$f" ]]; then
      cp -a "$f" "$deploy_dir/"
    fi
  done
fi

echo "[OK] mode=$mode target=${target:-all} -> $deploy_dir"
