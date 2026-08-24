{
  autoconf,
  autoPatchelfHook,
  clang,
  cmake,
  fetchurl,
  gcc,
  git,
  gnum4,
  gnumake,
  gnutar,
  lib,
  mercurial,
  nasm,
  ninja,
  nodejs_22,
  perl,
  pkg-config,
  python3,
  rsync,
  rustCbindgen,
  rustToolchain,
  stdenvNoCC,
  unzip,
  which,
  writeText,
  yasm,
  zip,
  zstd,
  engineSource,
}:

let
  version = "1.21.15b";
  target = "aarch64-apple-darwin";
  objectDirectory = "obj-${target}";

  # These are the exact Linux-hosted Darwin toolchains referenced by the
  # Firefox 154 task graph. Zen's own macOS release workflow consumes the
  # same Mozilla artifacts when it cross-compiles on Ubuntu.
  clangToolchainArchive = fetchurl {
    url = "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/WXa-dDRtTvSEns67DUz6ZA/artifacts/public/build/clang.tar.zst";
    hash = "sha256-bzNQ9iaYkikqENIv6+RXTK9oSOw8O+EUNaEvPhKhou8=";
  };
  cctoolsArchive = fetchurl {
    url = "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/GD3bBDylRhmSKsUrrbOREQ/artifacts/public/build/cctools.tar.zst";
    hash = "sha256-tvqFIyWi8SPO+D+9iKDpbsYBknEqz6n3tj3WWyMOEsk=";
  };

  # Mozilla's macOS SDK toolchain artifact is access-controlled, so reproduce
  # it from the exact Apple package and digest in Firefox's task graph.
  macosSdkPackage = fetchurl {
    url = "https://swcdn.apple.com/content/downloads/09/08/047-91568-A_Y1CFZWQCD4/4xekpyz43i26dbp4enxfro8eb1q7wiujh5/CLTools_macOSNMOS_SDK.pkg";
    hash = "sha512-Xbi1oGpImn0+xYfrt+Ab5VFjEoApkj/CTtytR/rs1ngwGTwNkeJkPuDpLyzMo3rfIOTELPjeV4Rmb4ZjY4tcxQ==";
  };
  macosSdk = stdenvNoCC.mkDerivation {
    pname = "macos-sdk";
    version = "26.5";
    dontUnpack = true;
    nativeBuildInputs = [ python3 ];
    buildPhase = ''
      runHook preBuild
      mkdir -p "$out"
      PYTHONPATH=${engineSource}/python/mozbuild \
        python3 ${engineSource}/taskcluster/scripts/misc/unpack-sdk.py \
          file://${macosSdkPackage} \
          5db8b5a06a489a7d3ec587ebb7e01be55163128029923fc24edcad47faecd67830193c0d91e2643ee0e92f2ccca37adf20e4c42cf8de5784666f8663638b5cc5 \
          Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
          "$out"
      runHook postBuild
    '';
    dontInstall = true;
    dontFixup = true;
  };

  mozconfig = writeText "zen-macos-cross-mozconfig" ''
    mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/${objectDirectory}

    ac_add_options --disable-bootstrap
    ac_add_options --host=x86_64-unknown-linux-gnu
    ac_add_options --target=${target}
    ac_add_options --with-macos-sdk=${macosSdk}
    ac_add_options --with-libclang-path=@clangToolchain@/lib
    ac_add_options --enable-linker=lld

    ac_add_options --enable-application=browser
    ac_add_options --enable-default-toolkit=cairo-cocoa
    ac_add_options --with-app-name=zen
    ac_add_options --with-app-basename=Zen
    ac_add_options --with-branding=browser/branding/release
    ac_add_options --with-distribution-id=app.zen-browser
    ac_add_options --enable-update-channel=release

    ac_add_options --enable-eme=widevine
    ac_add_options --enable-jxl
    ac_add_options --with-unsigned-addon-scopes=app,system
    ac_add_options --without-wasm-sandboxed-libraries

    ac_add_options --enable-optimize
    ac_add_options --enable-release
    ac_add_options --disable-debug
    ac_add_options --disable-debug-symbols
    ac_add_options --disable-lto
    ac_add_options --disable-tests
    ac_add_options --disable-crashreporter
    ac_add_options --disable-geckodriver
    ac_add_options --disable-rust-tests
    ac_add_options --disable-updater
    ac_add_options --disable-clang-plugin

    mk_add_options MOZILLA_OFFICIAL=1
    mk_add_options AUTOCLOBBER=1
    mk_add_options MOZ_DATA_REPORTING=
    mk_add_options MOZ_SERVICES_HEALTHREPORT=
    mk_add_options MOZ_TELEMETRY_REPORTING=
    mk_add_options MOZ_REQUIRE_SIGNING=
  '';
in
stdenvNoCC.mkDerivation {
  pname = "zen-browser-darwin-cross";
  inherit version;

  # These belong to unused Android compiler runtimes and cctools inspection
  # utilities, respectively; neither participates in the browser build.
  autoPatchelfIgnoreMissingDeps = [
    "liblog.so"
    "libLTO.so.19.1"
  ];

  src = engineSource;

  nativeBuildInputs = [
    autoconf
    autoPatchelfHook
    clang
    cmake
    gcc.cc.lib
    git
    gnum4
    gnumake
    gnutar
    mercurial
    nasm
    ninja
    nodejs_22
    perl
    pkg-config
    python3
    rsync
    rustCbindgen
    rustToolchain
    unzip
    which
    yasm
    zip
    zstd
  ];

  postUnpack = ''
    chmod -R u+w "$sourceRoot"
    patchShebangs "$sourceRoot/mach" "$sourceRoot/build"
  '';

  configurePhase = ''
    runHook preConfigure

    export HOME="$TMPDIR/home"
    export MOZBUILD_STATE_PATH="$TMPDIR/mozbuild"
    export MACH_BUILD_PYTHON_NATIVE_PACKAGE_SOURCE=system
    export MOZ_NOSPAM=1
    export MOZ_APP_REMOTINGNAME=zen
    export MOZ_APP_BASENAME=Zen
    export MOZ_APPUPDATE_HOST=updates.zen-browser.app
    export MOZILLA_OFFICIAL=1
    export SURFER_COMPAT=aarch64
    export SURFER_PLATFORM=darwin
    export ZEN_CROSS_COMPILING=1
    export ZEN_GA_DISABLE_PGO=true
    export ZEN_RELEASE=1
    export ZEN_RELEASE_BRANCH=release
    export SDKROOT=${macosSdk}
    # Some host-side Rust build helpers link C++ code and need the Linux C++
    # runtime. Keep this narrower than Mozilla's full Clang library directory,
    # which would override libraries used by Nix's native compiler wrapper.
    export LD_LIBRARY_PATH=${gcc.cc.lib}/lib

    mkdir -p "$HOME" "$MOZBUILD_STATE_PATH" "$TMPDIR/toolchains"
    tar --use-compress-program=unzstd -xf ${clangToolchainArchive} \
      -C "$TMPDIR/toolchains"
    tar --use-compress-program=unzstd -xf ${cctoolsArchive} \
      -C "$TMPDIR/toolchains"
    autoPatchelf "$TMPDIR/toolchains"

    substitute ${mozconfig} "$TMPDIR/mozconfig" \
      --subst-var-by clangToolchain "$TMPDIR/toolchains/clang"
    export MOZCONFIG="$TMPDIR/mozconfig"
    export PATH="$TMPDIR/toolchains/clang/bin:$TMPDIR/toolchains/cctools/bin:$PATH"
    # Keep the target and SDK on the compiler command itself. Firefox passes
    # this command through to Rust's cargo-linker; relying only on configure's
    # later LDFLAGS leaves standalone Rust programs unable to resolve libSystem.
    export CC="$TMPDIR/toolchains/clang/bin/clang --target=${target} -isysroot ${macosSdk} -mmacosx-version-min=11.0 -fuse-ld=lld"
    export CXX="$TMPDIR/toolchains/clang/bin/clang++ --target=${target} -isysroot ${macosSdk} -mmacosx-version-min=11.0 -stdlib=libc++ -fuse-ld=lld"
    # Host utilities must go through Nix's compiler wrapper so libc headers
    # and the Linux linker are available; target code uses Mozilla's Clang.
    export HOST_CC=${clang}/bin/clang
    export HOST_CXX=${clang}/bin/clang++
    # Firefox preprocesses .S sources through AS. Use Clang's integrated
    # assembler so target macros such as __APPLE__ select Mach-O syntax.
    export AS="$CC"
    export AR="$TMPDIR/toolchains/cctools/bin/${target}-ar"
    export RANLIB="$TMPDIR/toolchains/cctools/bin/${target}-ranlib"
    export STRIP="$TMPDIR/toolchains/cctools/bin/${target}-strip"

    ./mach configure

    runHook postConfigure
  '';

  buildPhase = ''
    runHook preBuild

    ./mach build -j8

    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall

    make -C ${objectDirectory} stage-package
    app="$(find ${objectDirectory}/dist -type d -name 'Zen.app' -print -quit)"
    test -n "$app"
    mkdir -p "$out/Applications"
    cp -R "$app" "$out/Applications/Zen.app"

    runHook postInstall
  '';

  dontFixup = true;
  enableParallelBuilding = true;

  meta = {
    description = "Zen Browser cross-compiled on Linux for Apple silicon macOS";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = lib.platforms.linux;
  };
}
