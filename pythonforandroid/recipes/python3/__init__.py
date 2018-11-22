from pythonforandroid.recipe import TargetPythonRecipe, Recipe
from pythonforandroid.toolchain import shprint, current_directory
from pythonforandroid.logger import logger, info, error
from pythonforandroid.util import ensure_dir, walk_valid_filens
from os.path import exists, join, dirname
from os import environ
import shutil
import glob
import sh

STDLIB_DIR_BLACKLIST = {
    '__pycache__',
    'curses'
    'ensurepip',
    'idlelib',
    'lib2to3',
    'test',
    'tests',
    'tkinter',
    'turtledemo',
    'venv',
    'wsgiref',
}


STDLIB_FILEN_BLACKLIST_COMMON = [
    '*.exe',
    '*.whl',
    'README',
    'README.txt',
    'distutils/command/command_template',
    'email/architecture.rst'
]

STDLIB_FILEN_BLACKLIST = STDLIB_FILEN_BLACKLIST_COMMON + ["*.pyc"]
STDLIB_ZIP_FILEN_BLACKLIST = STDLIB_FILEN_BLACKLIST_COMMON + ["*.py"]

# TODO: Move to a generic location so all recipes use the same blacklist
SITE_PACKAGES_DIR_BLACKLIST = {
    '__pycache__',
    'tests'
}

SITE_PACKAGES_FILEN_BLACKLIST = []


class Python3Recipe(TargetPythonRecipe):
    version = '3.7.1'
    url = 'https://www.python.org/ftp/python/{version}/Python-{version}.tgz'
    name = 'python3'

    depends = ['hostpython3']
    conflicts = ['python3crystax', 'python2']
    opt_depends = ['openssl', 'sqlite3']

    # This recipe can be built only against API 21+
    MIN_NDK_API = 21

    def build_arch(self, arch):
        if self.ctx.ndk_api < self.MIN_NDK_API:
            error('Target ndk-api is {}, but the python3 recipe supports only {}+'.format(
                self.ctx.ndk_api, self.MIN_NDK_API))
            exit(1)

        recipe_build_dir = self.get_build_dir(arch.arch)

        # Create a subdirectory to actually perform the build
        build_dir = join(recipe_build_dir, 'android-build')
        ensure_dir(build_dir)

        # TODO: Get these dynamically, like bpo-30386 does
        sys_prefix = '/usr/local'
        sys_exec_prefix = '/usr/local'

        # Skipping "Ensure that nl_langinfo is broken" from the original bpo-30386

        platform_name = 'android-{}'.format(self.ctx.ndk_api)

        with current_directory(build_dir):
            env = environ.copy()

            # TODO: Get this information from p4a's arch system
            android_host = 'arm-linux-androideabi'
            android_build = sh.Command(join(recipe_build_dir, 'config.guess'))().stdout.strip().decode('utf-8')
            platform_dir = join(self.ctx.ndk_dir, 'platforms', platform_name, 'arch-arm')
            toolchain = '{android_host}-4.9'.format(android_host=android_host)
            toolchain = join(self.ctx.ndk_dir, 'toolchains', toolchain, 'prebuilt', 'linux-x86_64')
            CC = '{clang} -target {target} -gcc-toolchain {toolchain}'.format(
                clang=join(self.ctx.ndk_dir, 'toolchains', 'llvm', 'prebuilt', 'linux-x86_64', 'bin', 'clang'),
                target='armv7-none-linux-androideabi',
                toolchain=toolchain)

            AR = join(toolchain, 'bin', android_host) + '-ar'
            LD = join(toolchain, 'bin', android_host) + '-ld'
            RANLIB = join(toolchain, 'bin', android_host) + '-ranlib'
            READELF = join(toolchain, 'bin', android_host) + '-readelf'
            STRIP = join(toolchain, 'bin', android_host) + '-strip --strip-debug --strip-unneeded'

            env['CC'] = CC
            env['AR'] = AR
            env['LD'] = LD
            env['RANLIB'] = RANLIB
            env['READELF'] = READELF
            env['STRIP'] = STRIP

            env['PATH'] = '{hostpython_dir}:{old_path}'.format(
                hostpython_dir=self.get_recipe('hostpython3', self.ctx).get_path_to_python(),
                old_path=env['PATH'])

            ndk_flags = ('--sysroot={ndk_sysroot} -D__ANDROID_API__={android_api} '
                         '-isystem {ndk_android_host}').format(
                             ndk_sysroot=join(self.ctx.ndk_dir, 'sysroot'),
                             android_api=self.ctx.ndk_api,
                             ndk_android_host=join(
                                 self.ctx.ndk_dir, 'sysroot', 'usr', 'include', android_host))
            sysroot = join(self.ctx.ndk_dir, 'platforms', platform_name, 'arch-arm')
            env['CFLAGS'] = env.get('CFLAGS', '') + ' ' + ndk_flags
            env['CPPFLAGS'] = env.get('CPPFLAGS', '') + ' ' + ndk_flags
            env['LDFLAGS'] = env.get('LDFLAGS', '') + ' --sysroot={} -L{}'.format(sysroot, join(sysroot, 'usr', 'lib'))

            if 'openssl' in self.ctx.recipe_build_order:
                recipe = Recipe.get_recipe('openssl', self.ctx)
                openssl_build_dir = recipe.get_build_dir(arch.arch)
                ensure_dir('Modules')
                setuplocal = join('Modules', 'Setup.local')
                shprint(sh.cp, join(self.get_recipe_dir(), 'Setup.local-ssl'), setuplocal)
                shprint(sh.sed, '-i.backup', 's#^SSL=.*#SSL={}#'.format(openssl_build_dir), setuplocal)
                env['OPENSSL_VERSION'] = recipe.lib_version

            if 'sqlite3' in self.ctx.recipe_build_order:
                # Include sqlite3 in python2 build
                recipe = Recipe.get_recipe('sqlite3', self.ctx)
                include = ' -I' + recipe.get_build_dir(arch.arch)
                lib = ' -L' + recipe.get_lib_dir(arch) + ' -lsqlite3'
                # Insert or append to env
                flag = 'CPPFLAGS'
                env[flag] = env[flag] + include if flag in env else include
                flag = 'LDFLAGS'
                env[flag] = env[flag] + lib if flag in env else lib

            # Manually add the libs directory, and copy some object
            # files to the current directory otherwise they aren't
            # picked up. This seems necessary because the --sysroot
            # setting in LDFLAGS is overridden by the other flags.
            # TODO: Work out why this doesn't happen in the original
            # bpo-30386 Makefile system.
            logger.warning('Doing some hacky stuff to link properly')
            lib_dir = join(sysroot, 'usr', 'lib')
            env['LDFLAGS'] += ' -L{}'.format(lib_dir)
            shprint(sh.cp, join(lib_dir, 'crtbegin_so.o'), './')
            shprint(sh.cp, join(lib_dir, 'crtend_so.o'), './')

            env['SYSROOT'] = sysroot

            if not exists('config.status'):
                shprint(sh.Command(join(recipe_build_dir, 'configure')),
                        *(' '.join(('--host={android_host}',
                                    '--build={android_build}',
                                    '--enable-shared',
                                    '--disable-ipv6',
                                    'ac_cv_file__dev_ptmx=yes',
                                    'ac_cv_file__dev_ptc=no',
                                    '--without-ensurepip',
                                    'ac_cv_little_endian_double=yes',
                                    '--prefix={prefix}',
                                    '--exec-prefix={exec_prefix}')).format(
                                        android_host=android_host,
                                        android_build=android_build,
                                        prefix=sys_prefix,
                                        exec_prefix=sys_exec_prefix)).split(' '), _env=env)

            if not exists('python'):
                shprint(sh.make, 'all', _env=env)

            # TODO: Look into passing the path to pyconfig.h in a
            # better way, although this is probably acceptable
            sh.cp('pyconfig.h', join(recipe_build_dir, 'Include'))

    def include_root(self, arch_name):
        return join(self.get_build_dir(arch_name),
                    'Include')

    def link_root(self, arch_name):
        return join(self.get_build_dir(arch_name),
                    'android-build')

    def create_python_bundle(self, dirn, arch):
        ndk_dir = self.ctx.ndk_dir
        hostpython = sh.Command(self.ctx.hostpython)

        # Bundle compiled python modules to a folder
        modules_dir = join(dirn, 'modules')
        ensure_dir(modules_dir)

        modules_build_dir = join(
            self.get_build_dir(arch.arch),
            'android-build',
            'build',
            'lib.linux-arm-3.7')
        module_filens = (glob.glob(join(modules_build_dir, '*.so')) +
                         glob.glob(join(modules_build_dir, '*.py')))
        for filen in module_filens:
            shutil.copy2(filen, modules_dir)

        # zip up the standard library
        # 1. copy only the files we want into the stdlib directory
        # 2. compile them
        # 3. remove some __pycache__ generated
        # 4. zip it
        stdlib_zip = join(dirn, 'stdlib.zip')
        stdlib_dir = join(dirn, 'stdlib')
        ensure_dir(stdlib_dir)

        with current_directory(join(self.get_build_dir(arch.arch), 'Lib')):
            stdlib_filens = walk_valid_filens(
                '.', STDLIB_DIR_BLACKLIST, STDLIB_FILEN_BLACKLIST)
            for filen in stdlib_filens:
                ensure_dir(join(stdlib_dir, dirname(filen)))
                shutil.copy2(filen, join(stdlib_dir, filen))

        with current_directory(stdlib_dir):
            shprint(hostpython, '-m', 'compileall', '-f', '-b')
            stdlib_filens = walk_valid_filens(
                '.', STDLIB_DIR_BLACKLIST, STDLIB_ZIP_FILEN_BLACKLIST)
            shprint(sh.zip, stdlib_zip, *stdlib_filens)

        # copy & trim the site-packages into place
        site_package_dir = join(dirn, 'site-packages')
        ensure_dir(site_package_dir)
        # TODO: Improve the API around walking and copying the files
        with current_directory(self.ctx.get_python_install_dir()):
            filens = list(walk_valid_filens(
                '.', SITE_PACKAGES_DIR_BLACKLIST, SITE_PACKAGES_FILEN_BLACKLIST))
            for filen in filens:
                ensure_dir(join(site_package_dir, dirname(filen)))
                shutil.copy2(filen, join(site_package_dir, filen))

        # trim site-packages
        # XXX maybe export that as a function, and make it available for
        # every package that goes into site-packages?
        with current_directory(site_package_dir):
            shprint(hostpython, '-m', 'compileall', '-f', '-b')
            sh.find(".", "-iname", "*.py", "-delete")
            # some pycache are recreated after compileall
            sh.find(".", "-path", "*/__pycache__/*", "-delete")
            sh.find(".", "-name", "__pycache__", "-type", "d", "-delete")

        # copy the python .so files into place
        python_build_dir = join(self.get_build_dir(arch.arch),
                                'android-build')
        shprint(sh.cp,
                join(python_build_dir,
                     'libpython{}m.so'.format(self.major_minor_version_string)),
                'libs/{}'.format(arch.arch))
        shprint(sh.cp,
                join(python_build_dir,
                     'libpython{}m.so.1.0'.format(self.major_minor_version_string)),
                'libs/{}'.format(arch.arch))

        info('Renaming .so files to reflect cross-compile')
        self.reduce_object_file_names(join(dirn, 'site-packages'))

        return join(dirn, 'site-packages')


recipe = Python3Recipe()
