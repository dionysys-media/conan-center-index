from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.apple import fix_apple_shared_install_name, is_apple_os
from conan.tools.env import VirtualBuildEnv
from conan.tools.files import apply_conandata_patches, copy, export_conandata_patches, get, rm, rmdir
from conan.tools.gnu import Autotools, AutotoolsToolchain
from conan.tools.layout import basic_layout
from conan.tools.microsoft import is_msvc, unix_path
from conan.tools.scm import Version

from textwrap import dedent, fill
import os
import stat

required_conan_version = ">=1.56.0"


class GmpConan(ConanFile):
    name = "gmp"
    license = ("LGPL-3.0", "GPL-2.0")  # "Since GMP 6.0"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://gmplib.org"
    description = "\n".join((
        "GNU Multiple Precision Arithmetic Library",
        "GNU MP is a portable library written in C for arbitrary precision "
        "arithmetic on integers, rational numbers, and floating-point numbers.",
        "It aims to provide the fastest possible arithmetic for all "
        "applications that need higher precision than is directly supported by"
        " the basic C types."
    ))
    topics = ("gmp", "math", "arbitrary", "precision")

    settings = "os", "compiler", "build_type", "arch"

    options = {
        "shared":          [True, False],
        "fPIC":            [True, False],
        "assembly":        [True, False],
        "cxx":             [True, False],
        "fat":             [True, False],
        "alloca":          [
            "alloca",
            "malloc-reentrant",
            "malloc-notreentrant",
            "reentrant",
            "notreentrant",
            "debug",
        ],
        "fft":             [True, False],
        "old_fft_full":    [True, False],
        "assertions":      [True, False],
        "profiling":       ["prof", "gprof", "instrument", None],
        "nails":           [True, *range(0, 64)],
        "minithres":       [True, False],
        "fake_cpuid":      [True, False],
        "maintainer_mode": [True, False],
        "with_aix_soname": ["aix", "svr4", "both"],
        "with_gnu_ld":     [True, False],
        "run_checks":      [True, False],
    }

    default_options = {
        "shared":          False,
        "fPIC":            False,
        "assembly":        True,
        "cxx":             False,
        "fat":             False,
        "alloca":          "reentrant",
        "fft":             True,
        "old_fft_full":    False,
        "assertions":      False,
        "profiling":       None,
        "nails":           0,
        "minithres":       False,
        "fake_cpuid":      False,
        "maintainer_mode": False,
        "with_aix_soname": "aix",
        "with_gnu_ld":     False,
        "run_checks":      True,
    }

    @staticmethod
    def _format_description(description):
        first, rest = description.strip.lsplit('\n', 1)
        return fill('\n'.join((first, dedent(rest))), drop_whitespace=False, subsequent_indent=' ' * 4)

    options_description = {
        option: description for option, _format_description(description) in {
            "shared":
                """Build shared libraries rather than static libraries.

                N.b. Some platforms are incompatible with shared/static libraries.
                """,
            "fPIC":
                """Build static libraries with Position Independent Code.

                Note: Implicitly removed if shared is enabled or on platforms
                    where all object code is implicitly PIC.
                """,
            "assembly":
                """Generic C code can be selected with this option set to False.

                Note: Disabling will run quite slowly, but it should be portable
                    and should at least make it possible to get something
                    running if all else fails.
                """,
            "cxx":
                """C++ support.

                The C++ support consists of a library libgmpxx.la and header file gmpxx.h.

                libgmpxx.la will use certain internals from libgmp.la and can only
                    be expected to work with libgmp.la from the same GMP version.

                Defaulted to False to avoid a build failure (when the C++ and C
                    compilers do not appropriately match) Since the internal
                    configure script cannot easily detect this.
                """,
            "fat":
                """Selects a "fat binary" build on x86 / x86_64.

                Optimized low level subroutines are chosen at runtime according
                    to the CPU detected. This means more code, but gives good
                    performance on all x86 chips.

                Note: This option might become available for more architectures
                    in the future. In the interim this option is removed from
                    other (host) architectures.
                """,
            "alloca":
                """Method for selecting temporary workspace memory.

                Standard methods:
                    * "alloca" - C library or compiler builtin.
                        Reentrant and fast, recommended. It actually allocates
                        just small blocks on the stack; larger ones use
                        "malloc-reentrant" (regardless).
                    * "malloc-reentrant" - the heap, in a re-entrant fashion.
                        Reentrant and thread safe, but "malloc-notreentrant"
                        is faster and should be used if reentrancy is not
                        required.
                    * "malloc-notreentrant" - the heap, with global variables.

                Convenience methods:
                    * "reentrant" - alloca if available, otherwise "malloc-reentrant".
                        This is the default.
                    * "notreentrant" - alloca if available, otherwise "malloc-notreentrant".
                    * "debug" - to help when debugging memory related problems.
                        A warning is emitted for `build_type`s other than "Debug", and
                        "RelWithDebInfo".

                The two 'malloc' methods in fact use the memory allocation functions
                selected by mp_set_memory_functions, these being malloc and
                friends by default.
                """,
            "fft":
                """FFT support for multiplications.

                By default multiplications are done using Karatsuba, 3-way Toom,
                    higher degree Toom, and Fermat FFT. The FFT is only used on
                    large to very large operands and can be disabled to save
                    code size if desired.
                """,
            "old_fft_full":
                """Provide the old "mpn_mul_fft_full" algorithm.

                N.b. The standard mpn_fft_mul algorithm is unconditionally
                    aliased (hard-coded) to mpn_nussbaumer_full, regardless of
                    this option. 
                """,
            "assertions":
                """Consistency checking within the library.

                A warning is emitted for `build_type`s other than "Debug", and
                    "RelWithDebInfo".
                """,
            "profiling":
                """Detailed profiling support.

                Several methods are available:
                    * None - no profiling (default).
                    * "prof" - support for the system prof.
                        Provides call counting in addition to program counter
                        sampling, which allows the most frequently called
                        routines to be identified, and an average time spent in
                        each routine to be determined.
                        On processors other than x86 / x86_64, assembly
                        routines will be as if compiled without this and
                        therefore won’t appear in the call counts.
                        N.b. gprof flat profile and call counts can be expected
                        to be valid, but not any call graphs.
                    * "gprof" - support for gprof (additional call graph support).
                        Provides call graph construction in addition to call
                        counting and program counter sampling, which makes it
                        possible to count calls coming from different locations.
                        On processors other than x86 / x86_64, assembly
                        routines will be as if compiled without this
                        and therefore won’t appear in the call counts.
                        On x86 /x86_64 and m86k systems this is incompatible
                        with "-fomit-frame-pointer", so the latter is omitted
                        from the internal default flags in that case, which
                        might result in poorer code generation.
                    * "instrumentation" - function instrumentation via "-finstrument-functions".
                        Inserts special instrumenting calls at the start and
                        end of each function, allowing exact timing and full
                        call graph construction.
                        Instrumenting is not normally a standard system feature
                        and will require support from an external library to be
                        linked, such as "fc" (fnccheck / Function Check); or
                        any custom library that implements the instrumentation
                        functions added by the compiler. Names and details are
                        compiler specific, and the compiler will not necessarily
                        provide stub functions.
                """,
            "nails":
                """Experimental: number of bits left at the top of mp_limb_t

                This can significantly improve carry handling on some processors.

                By default the number of bits will be chosen according to what
                    suits the host processor, but a particular number can be
                    selected.

                Some presets are recommended depending on the architecture in
                    mailing lists and documents provided in-source.

                At the mpn level, a nail build is neither source nor binary
                    compatible with a non-nail build, strictly speaking. But
                    programs acting on limbs only through the mpn functions are
                    likely to work equally well with either build, and
                    judicious use of nail-related macros provided should make
                    any program compatible with either build, at the source level.

                For the higher level routines, meaning mpz etc, a nail build
                    should be fully source and binary compatible with a non-nail
                    build.

                N.b. True is equivalent to an internal preset constant value.
                N.b. Must be less than the number of GMP_LIMB_BITS, which is
                    implicitly implementation defined at build time.
                Additional resources:
                    https://gmplib.org/list-archives/gmp-discuss/2007-June/002783.html
                """,
            "with_aix_soname":
                """Shared library (aka "SONAME") variant to provide on AIX.
                
                N.b. this option is ignored outside AIX architectures.
                """,
            "silent_rules":
                """Less verbose output from make.
                """,
            "tune":
                """Tune the build provided some parameters.
                
                This should either be a path to some parameter file, the string
                    "native", or None. None disables specific tuning, "native"
                    is invalid if cross-building.
                """,
            "tune_args":
                """When tune is native, use these args instead of internal defaults.
                
                Format is a space separated string representing the arguments or
                    None. The string will be normalized. For example, if the
                    program is "./tuneup", you would set
                    `-o tune_args="-f     5  -o    -t  -t"`, which will be
                    normalized and executed as "./tuneup -f 5 -o -t -t" in a Unix
                    shell. The normalized form of the arguments constitute the
                    info used in the package id.
                
                This format was chosen out of necessity, due to partially
                    undocumented, yet useful, variations of the command. Reading
                    the code of the tuneup executable, located in the "tune"
                    sub-folder of the source code, is recommended for experienced
                    users. Casual users should just follow recommendations from
                    the publicly available GMP manual.
                    
                The internal defaults are computed from other options set in
                    an undocumented manner.
                """,
            "microarch":
                """The host micro-architecture.
                
                Values include None (default), meaning use the conan
                    provided triplet, "native", meaning let GMP guess for you,
                    only valid if not cross building, or any other string.
                    
                N.b. The micro-architectures are not validated when cross building,
                    because data provided by GMP source code is difficult to
                    parse, names can change (GMP chosen), and various CPUs lie
                    about their micro-architecture and can possibly trick the
                    GMP guess script, as well as any user-written code to
                    determine the micro-architecture of a system. For this
                    reason, anything other than "native".
                """,
            "minithres":
                """Minimal mpn thresholds for testing.

                N.b. this option is generally undocumented and thus only valid
                    in package developer mode.                
                """,
            "fake_cpuid":
                """GMP_CPU_TYPE faking cpuid.

                N.b. this option is generally undocumented and thus only valid
                    in package developer mode.                
                """,
            "maintainer_mode":
                """Additional make rules and dependencies useful for maintainers.

                N.b. this option only makes sense and is valid in package
                    developer mode.                
                """,
            "with_gnu_ld":
                """Assume the C compiler uses GNU ld.

                N.b. this option is mostly unnecessary for conan and only valid
                    in package developer mode.
                """,
            "libtool_lock":
                """Whether or not to engage the libtool lock. Default is True.

                N.b. this can break builds and is therefore only valid
                    in package developer mode.
                """,
        }.items()
    }

    @property
    def _settings_build(self):
        return getattr(self, "settings_build", self.settings)

    def export_sources(self):
        export_conandata_patches(self)

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC
        if self.settings.arch not in ["x86", "x86_64"]:
            del self.options.enable_fat

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")
        if self.options.get_safe("enable_fat"):
            del self.options.enable_assembly
        if not self.options.enable_cxx:
            self.settings.rm_safe("compiler.libcxx")
            self.settings.rm_safe("compiler.cppstd")

    def layout(self):
        basic_layout(self, src_folder="src")

    def package_id(self):
        del self.info.options.run_checks  # run_checks doesn't affect package's ID

    def validate(self):
        if is_msvc(self) and self.options.shared:
            raise ConanInvalidConfiguration(
                f"{self.ref} cannot be built as a shared library using Visual Studio: some error occurs at link time",
            )

    def build_requirements(self):
        # require an autotools toolchain if on non-Linux or git-checkout (recreate configure)

        # require coreutils, m4, libtool if on non-Linux (not normally system-available)
        # self.tool_requires("m4/1.4.19")

        # maybe require binutils on non-Linux? unclear if some are coreutils or binutils

        if self._settings_build.os == "Windows":
            self.win_bash = True
            if not self.conf.get("tools.microsoft.bash:path", check_type=str):
                self.tool_requires("msys2/cci.latest")

        if is_msvc(self):
            self.tool_requires("yasm/1.3.0")       # Needed for determining 32-bit word size
            self.tool_requires("automake/1.16.5")  # Needed for lib-wrapper

    def source(self):
        get(self, **self.conan_data["sources"][self.version],
            destination=self.source_folder, strip_root=True)

    def generate(self):
        def yes_no(v):
            return "yes" if v else "no"

        env = VirtualBuildEnv(self)
        env.generate()

        tc = AutotoolsToolchain(self)
        tc.configure_args.extend([
            f'--with-pic={yes_no(self.options.get_safe("fPIC", True))}',
            f'--enable-assembly={yes_no(self.options.get_safe("enable_assembly", False))}',
            f'--enable-fat={yes_no(self.options.get_safe("enable_fat", False))}',
            f'--enable-cxx={yes_no(self.options.enable_cxx)}',
        ])

        # Use relative path to avoid issues with #include "$srcdir/gmp-h.in" on Windows
        if self._settings_build.os == "Windows":
            tc.configure_args.append(f'--srcdir=../src')

        if is_msvc(self):
            tc.configure_args.extend([
                "ac_cv_c_restrict=restrict",
                "gmp_cv_asm_label_suffix=:",
                # added to get further in shared MSVC build, but it gets stuck later
                "lt_cv_sys_global_symbol_pipe=cat",
            ])
            tc.extra_cxxflags.append("-EHsc")
            if (self.settings.compiler == "msvc" and Version(self.settings.compiler.version) >= "180") or \
               (self.settings.compiler == "Visual Studio" and Version(self.settings.compiler.version) >= "12"):
                tc.extra_cflags.append("-FS")
                tc.extra_cxxflags.append("-FS")

        env = tc.environment()  # Environment must be captured *after* setting extra_cflags, etc. to pick up changes

        if is_msvc(self):
            yasm_wrapper = unix_path(self, os.path.join(self.source_folder, "yasm_wrapper.sh"))
            yasm_machine = {
                "x86": "x86",
                "x86_64": "amd64",
            }[str(self.settings.arch)]
            ar_wrapper = unix_path(self, self.conf.get("user.automake:lib-wrapper"))
            dumpbin_nm = unix_path(self, os.path.join(self.source_folder, "dumpbin_nm.py"))
            env.define("CC", "cl -nologo")
            env.define("CCAS", f"{yasm_wrapper} -a x86 -m {yasm_machine} -p gas -r raw -f win32 -g null -X gnu")
            env.define("CXX", "cl -nologo")
            env.define("LD", "link -nologo")
            env.define("AR", f'{ar_wrapper} "lib -nologo"')
            env.define("NM", f"python {dumpbin_nm}")

        tc.generate(env)

    def _patch_sources(self):
        apply_conandata_patches(self)
        # Fix permission issue
        if is_apple_os(self):
            configure_file = os.path.join(self.source_folder, "configure")
            configure_stats = os.stat(configure_file)
            os.chmod(configure_file, configure_stats.st_mode | stat.S_IEXEC)

    def build(self):
        self._patch_sources()
        autotools = Autotools(self)
        autotools.configure()
        autotools.make()
        # INFO: According to the gmp readme file, make check should not be omitted, but it causes timeouts in CI.
        if self.options.run_checks:
            autotools.make(target="check")

    def package(self):
        copy(self, "COPYINGv2", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
        copy(self, "COPYING.LESSERv3", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
        autotools = Autotools(self)
        autotools.install()
        rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))
        rmdir(self, os.path.join(self.package_folder, "share"))
        rm(self, "*.la", os.path.join(self.package_folder, "lib"))
        fix_apple_shared_install_name(self)

    def package_info(self):
        # Workaround to always provide a pkgconfig file depending on all components
        self.cpp_info.set_property("pkg_config_name", "gmp-all-do-not-use")

        self.cpp_info.components["libgmp"].set_property("pkg_config_name", "gmp")
        self.cpp_info.components["libgmp"].libs = ["gmp"]
        if self.options.enable_cxx:
            self.cpp_info.components["gmpxx"].set_property("pkg_config_name", "gmpxx")
            self.cpp_info.components["gmpxx"].libs = ["gmpxx"]
            self.cpp_info.components["gmpxx"].requires = ["libgmp"]
            if self.settings.os != "Windows":
                self.cpp_info.components["gmpxx"].system_libs = ["m"]

        # TODO: to remove in conan v2 once cmake_find_package_* generators removed
        #       GMP doesn't have any official CMake Find nor config file, do not port these names to CMakeDeps
        self.cpp_info.names["pkg_config"] = "gmp-all-do-not-use"
        self.cpp_info.components["libgmp"].names["cmake_find_package"] = "GMP"
        self.cpp_info.components["libgmp"].names["cmake_find_package_multi"] = "GMP"
        if self.options.enable_cxx:
            self.cpp_info.components["gmpxx"].names["cmake_find_package"] = "GMPXX"
            self.cpp_info.components["gmpxx"].names["cmake_find_package_multi"] = "GMPXX"
