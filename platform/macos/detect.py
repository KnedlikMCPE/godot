import os
import sys
from methods import detect_darwin_sdk_path, get_compiler_version, is_vanilla_clang
from platform_methods import detect_arch, detect_mvk

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from SCons.Script.SConscript import SConsEnvironment


def get_name():
    return "macOS"


def can_build():
    if sys.platform == "darwin" or ("OSXCROSS_ROOT" in os.environ):
        return True

    return False


def get_opts():
    from SCons.Variables import BoolVariable, EnumVariable

    return [
        ("osxcross_sdk", "OSXCross SDK version", "darwin16"),
        ("MACOS_SDK_PATH", "Path to the macOS SDK", ""),
        ("vulkan_sdk_path", "Path to the Vulkan SDK", ""),
        EnumVariable("macports_clang", "Build using Clang from MacPorts", "no", ("no", "5.0", "devel")),
        BoolVariable("use_ubsan", "Use LLVM/GCC compiler undefined behavior sanitizer (UBSAN)", False),
        BoolVariable("use_asan", "Use LLVM/GCC compiler address sanitizer (ASAN)", False),
        BoolVariable("use_tsan", "Use LLVM/GCC compiler thread sanitizer (TSAN)", False),
        BoolVariable("use_coverage", "Use instrumentation codes in the binary (e.g. for code coverage)", False),
        ("angle_libs", "Path to the ANGLE static libraries", ""),
        (
            "bundle_sign_identity",
            "The 'Full Name', 'Common Name' or SHA-1 hash of the signing identity used to sign editor .app bundle.",
            "-",
        ),
        BoolVariable("generate_bundle", "Generate an APP bundle after building iOS/macOS binaries", False),
    ]


def get_doc_classes():
    return [
        "EditorExportPlatformMacOS",
    ]


def get_doc_path():
    return "doc_classes"


def get_flags():
    return [
        ("arch", detect_arch()),
        ("use_volk", False),
        ("supported", ["mono"]),
    ]


def configure(env: "SConsEnvironment"):
    # Validate arch.
    supported_arches = ["x86_64", "arm64"]
    if env["arch"] not in supported_arches:
        print(
            'Unsupported CPU architecture "%s" for macOS. Supported architectures are: %s.'
            % (env["arch"], ", ".join(supported_arches))
        )
        sys.exit()

    ## Build type

    if env["target"] == "template_release":
        if env["arch"] != "arm64":
            env.Prepend(CCFLAGS=["-msse2"])
    elif env.dev_build:
        env.Prepend(LINKFLAGS=["-Xlinker", "-no_deduplicate"])

    ## Compiler configuration

    # Save this in environment for use by other modules
    if "OSXCROSS_ROOT" in os.environ:
        env["osxcross"] = True

    # CPU architecture.
    if env["arch"] == "arm64":
        print("Building for macOS 11.0+.")
        env.Append(ASFLAGS=["-arch", "arm64", "-mmacosx-version-min=11.0"])
        env.Append(CCFLAGS=["-arch", "arm64", "-mmacosx-version-min=11.0"])
        env.Append(LINKFLAGS=["-arch", "arm64", "-mmacosx-version-min=11.0"])
    elif env["arch"] == "x86_64":
        print("Building for macOS 10.15+.")
        env.Append(ASFLAGS=["-arch", "x86_64", "-mmacosx-version-min=10.15"])
        env.Append(CCFLAGS=["-arch", "x86_64", "-mmacosx-version-min=10.15"])
        env.Append(LINKFLAGS=["-arch", "x86_64", "-mmacosx-version-min=10.15"])

    cc_version = get_compiler_version(env)
    cc_version_major = cc_version["apple_major"]
    cc_version_minor = cc_version["apple_minor"]
    vanilla = is_vanilla_clang(env)

    # Workaround for Xcode 15 linker bug.
    if not vanilla and cc_version_major == 1500 and cc_version_minor == 0:
        env.Prepend(LINKFLAGS=["-ld_classic"])

    env.Append(CCFLAGS=["-fobjc-arc"])

    if not "osxcross" in env:  # regular native build
        if env["macports_clang"] != "no":
            mpprefix = os.environ.get("MACPORTS_PREFIX", "/opt/local")
            mpclangver = env["macports_clang"]
            env["CC"] = mpprefix + "/libexec/llvm-" + mpclangver + "/bin/clang"
            env["CXX"] = mpprefix + "/libexec/llvm-" + mpclangver + "/bin/clang++"
            env["AR"] = mpprefix + "/libexec/llvm-" + mpclangver + "/bin/llvm-ar"
            env["RANLIB"] = mpprefix + "/libexec/llvm-" + mpclangver + "/bin/llvm-ranlib"
            env["AS"] = mpprefix + "/libexec/llvm-" + mpclangver + "/bin/llvm-as"
        else:
            env["CC"] = "clang"
            env["CXX"] = "clang++"

        detect_darwin_sdk_path("macos", env)
        env.Append(CCFLAGS=["-isysroot", "$MACOS_SDK_PATH"])
        env.Append(LINKFLAGS=["-isysroot", "$MACOS_SDK_PATH"])

    else:  # osxcross build
        root = os.environ.get("OSXCROSS_ROOT", "")
        if env["arch"] == "arm64":
            basecmd = root + "/target/bin/arm64-apple-" + env["osxcross_sdk"] + "-"
        else:
            basecmd = root + "/target/bin/x86_64-apple-" + env["osxcross_sdk"] + "-"

        ccache_path = os.environ.get("CCACHE")
        if ccache_path is None:
            env["CC"] = basecmd + "cc"
            env["CXX"] = basecmd + "c++"
        else:
            # there aren't any ccache wrappers available for macOS cross-compile,
            # to enable caching we need to prepend the path to the ccache binary
            env["CC"] = ccache_path + " " + basecmd + "cc"
            env["CXX"] = ccache_path + " " + basecmd + "c++"
        env["AR"] = basecmd + "ar"
        env["RANLIB"] = basecmd + "ranlib"
        env["AS"] = basecmd + "as"

    # LTO

    if env["lto"] == "auto":  # LTO benefits for macOS (size, performance) haven't been clearly established yet.
        env["lto"] = "none"

    if env["lto"] != "none":
        if env["lto"] == "thin":
            env.Append(CCFLAGS=["-flto=thin"])
            env.Append(LINKFLAGS=["-flto=thin"])
        else:
            env.Append(CCFLAGS=["-flto"])
            env.Append(LINKFLAGS=["-flto"])

    # Sanitizers

    if env["use_ubsan"] or env["use_asan"] or env["use_tsan"]:
        env.extra_suffix += ".san"
        env.Append(CCFLAGS=["-DSANITIZERS_ENABLED"])

        if env["use_ubsan"]:
            env.Append(
                CCFLAGS=[
                    "-fsanitize=undefined,shift,shift-exponent,integer-divide-by-zero,unreachable,vla-bound,null,return,signed-integer-overflow,bounds,float-divide-by-zero,float-cast-overflow,nonnull-attribute,returns-nonnull-attribute,bool,enum,vptr,pointer-overflow,builtin"
                ]
            )
            env.Append(LINKFLAGS=["-fsanitize=undefined"])
            env.Append(CCFLAGS=["-fsanitize=nullability-return,nullability-arg,function,nullability-assign"])

        if env["use_asan"]:
            env.Append(CCFLAGS=["-fsanitize=address,pointer-subtract,pointer-compare"])
            env.Append(LINKFLAGS=["-fsanitize=address"])

        if env["use_tsan"]:
            env.Append(CCFLAGS=["-fsanitize=thread"])
            env.Append(LINKFLAGS=["-fsanitize=thread"])

    if env["use_coverage"]:
        env.Append(CCFLAGS=["-ftest-coverage", "-fprofile-arcs"])
        env.Append(LINKFLAGS=["-ftest-coverage", "-fprofile-arcs"])

    ## Dependencies

    if env["builtin_libtheora"] and env["arch"] == "x86_64":
        env["x86_libtheora_opt_gcc"] = True

    ## Flags

    env.Prepend(CPPPATH=["#platform/macos"])
    env.Append(CPPDEFINES=["MACOS_ENABLED", "UNIX_ENABLED", "COREAUDIO_ENABLED", "COREMIDI_ENABLED"])
    env.Append(
        LINKFLAGS=[
            "-framework",
            "Cocoa",
            "-framework",
            "Carbon",
            "-framework",
            "AudioUnit",
            "-framework",
            "CoreAudio",
            "-framework",
            "CoreMIDI",
            "-framework",
            "IOKit",
            "-framework",
            "GameController",
            "-framework",
            "CoreHaptics",
            "-framework",
            "CoreVideo",
            "-framework",
            "AVFoundation",
            "-framework",
            "CoreMedia",
            "-framework",
            "QuartzCore",
            "-framework",
            "Security",
        ]
    )
    env.Append(LIBS=["pthread", "z"])

    if env["opengl3"]:
        env.Append(CPPDEFINES=["GLES3_ENABLED"])
        if env["angle_libs"] != "":
            env.AppendUnique(CPPDEFINES=["EGL_STATIC"])
            env.Append(LINKFLAGS=["-L" + env["angle_libs"]])
            env.Append(LINKFLAGS=["-lANGLE.macos." + env["arch"]])
            env.Append(LINKFLAGS=["-lEGL.macos." + env["arch"]])
            env.Append(LINKFLAGS=["-lGLES.macos." + env["arch"]])
        env.Prepend(CPPPATH=["#thirdparty/angle/include"])

    env.Append(LINKFLAGS=["-rpath", "@executable_path/../Frameworks", "-rpath", "@executable_path"])

    if env["vulkan"]:
        env.Append(CPPDEFINES=["VULKAN_ENABLED", "RD_ENABLED"])
        env.Append(LINKFLAGS=["-framework", "Metal", "-framework", "IOSurface"])
        if not env["use_volk"]:
            env.Append(LINKFLAGS=["-lMoltenVK"])

            mvk_path = ""
            arch_variants = ["macos-arm64_x86_64", "macos-" + env["arch"]]
            for arch in arch_variants:
                mvk_path = detect_mvk(env, arch)
                if mvk_path != "":
                    mvk_path = os.path.join(mvk_path, arch)
                    break

            if mvk_path != "":
                env.Append(LINKFLAGS=["-L" + mvk_path])
            else:
                print(
                    "MoltenVK SDK installation directory not found, use 'vulkan_sdk_path' SCons parameter to specify SDK path."
                )
                sys.exit(255)
