#pkg update && pkg upgrade -y
#pkg install binutils ndk-sysroot clang rust make -y


export CARGO_BUILD_TARGET="$(rustc -Vv | grep "host" | awk '{print $2}')"
#armv7-linux-androideabi

pip install maturin==1.10.2 --no-build-isolation --force-reinstall --verbose
