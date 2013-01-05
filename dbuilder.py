#!/usr/bin/env python
"""
Build a Win32 distribution for a Django project. Optionally include a
stripped down Python runtime distribution and the Django distribution.

Copyright: Stuart Rackham (c) 2008
License:   MIT
Email:     srackham@methods.co.nz

"""

VERSION = '0.7.0'

import sys
import os
import os.path
import fnmatch
import shutil
import py_compile
import subprocess
import glob
import tarfile
import re

######################################################################
# Default configuration parameters and match lists.
# To override the parameters or augment the match lists
# create a separate configuration file (see --conf-file option).
#
# Don't change DJANGO_RUNTIME_DIR else your project won't see Django.
######################################################################

# Default file and directory names.
DIST_DIR = 'dist'   # Distribution target directory relatve to PROJECT_DIR.
ISS_FILE = 'setup/setup.iss'    # Default --iss-file=- option value (relatve to PROJECT_DIR).
TARBALL_FILE = None             # Default --tarball=- option value (relatve to PROJECT_DIR).
PYTHON_RUNTIME_DIR = 'python'   # Destination relative to DIST_DIR.
DJANGO_RUNTIME_DIR = 'django'   # Destination relative to DIST_DIR.
INNO_SETUP_COMPILER = 'c:/Program Files/Inno Setup 5/ISCC.exe'
CONF_FILE = 'dbuilder.conf'     # Default optional configuration file name.
# Source directories for Python and Django runtime files.
# If relative path names are used they are relative to PROJECT_DIR.
PYTHON_DIR = 'c:/python25'
DJANGO_DIR = os.path.join(PYTHON_DIR,'Lib/site-packages/django')

# Project file (relative to PROJECT_DIR).
PROJECT_COPY_FILES = [
    '*',
    '!tags', '!*/tags',
    '!*.BAK',
    '!*.OLD',
    '!*.orig',
    '!*~',
    '!COMMIT', '!TODO',
    '!Session.vim', '!*/Session.vim',
    '!BAK/*', '!*/BAK/*',
    '!OLD/*', '!*/OLD/*',
    '!doc/*',
    '!setup/*',
    '!tarballs/*',
]

# Files for Django runtime (relative to DJANGO_DIR).
DJANGO_COPY_FILES = [
    '*',
    # Exclude all locales apart from English.
    '!conf/locale/*',
    'conf/locale/en/*',
]

# Files from the Python Windows install directory required by the Python
# runtime. The files selected will depend on both the Python version and Django
# project requirements.
PYTHON_COPY_FILES = [
    '*',
    '!Doc/*',
    '!include/*',
    '!Lib/bsddb/*',
    '!Lib/compiler/*',
    '!Lib/ctypes/*',
    '!Lib/curses/*',
    '!Lib/distutils/*',
    '!Lib/hotshot/*',
    '!Lib/idlelib/*',
    '!Lib/lib-tk/*',
    '!Lib/logging/*',
    '!Lib/msilib/*',
    '!Lib/site-packages/*',
    'Lib/site-packages/markdown.py',
    '!Lib/test/*', '!Lib/*/test/*',
    '!Lib/xml/*',
    '!LICENSE.txt',
    '!NEWS.txt',
    '!py2exe-wininst.log',
    '!pywin32-wininst.log',
    '!README.txt',
    '!Removepy2exe.exe',
    '!Removepywin32.exe',
    '!Scripts/*',
    '!tcl/*',
    '!Tools/*',
]

# Files from the Windows system32 directory that are required by the Python
# runtime. These files are Python version dependent.
PYTHON_SYSTEM_FILES = [
    'c:/windows/system32/python25.dll',
    'c:/windows/system32/msvcr71.dll',
]

# Executed before distribution is built.
# NOTE: Executed regardless of whether OPTIONS.dry_run is True or False.
def pre_build():
    pass

# Executed after distribution has been built but before Inno Setup is run.
# NOTE: Executed regardless of whether OPTIONS.dry_run is True or False.
def post_build():
    pass

######################################################################
# End of configuration parameters.
######################################################################


OPTIONS = None  # Parsed command-line options OptionParser object.


#####################
# Utility functions #
#####################

def errmsg(msg):
    sys.stderr.write('%s\n' % msg)

def infomsg(msg):
    print msg

def die(msg):
    errmsg('\nERROR: %s' % msg)
    errmsg("       view options with '%s --help'" % os.path.basename(__file__))
    sys.exit(1)

def verbose(msg):
    if OPTIONS.verbose or OPTIONS.dry_run:
        infomsg(msg)

def load_conf(conf_file):
    """
    Import optional configuration file which is used to override global
    configuration settings.
    """
    execfile(conf_file, globals())

def matches(path, match_list, context_dir):
    """
    Return true if the path matches any of the wildcards in 'match_list'.
    Relative 'match_list' wildcards are relative to the 'context_dir'.

    A match list is an ordered set of wildcards (optionally prefixed with a !
    character) and are used to filter a set of path names.

    A path is matched by matching in order against all wildcards in the list,
    if a path matches a wilcard it is considered matched unless it is
    subsequently unmatched by an exclusion (! prefixed) wildcard.

    Wildcards conform to the fnmatch module's notion of wildcards.

    """
    result = False
    for m in match_list:
        if m.startswith('!'):
            is_match = False
            pattern = m[1:]
        else:
            is_match = True
            pattern = m
        pattern = os.path.join(context_dir, pattern)
        if fnmatch.fnmatch(path, pattern):
            result = is_match
    return result

def dst_path(path, src_dir, dst_dir):
    """
    Translate source path to destination path.
    'path' must lie within the 'src_dir'.
    Return absoute path name.
    """
    path = os.path.abspath(path)
    src_dir = os.path.abspath(src_dir)
    dst_dir = os.path.abspath(dst_dir)
    return dst_dir + path[len(src_dir):]


###########
# Helpers #
###########

# For use by pre_build and post_build conf file functions.

def expand_path(filename, default_dir):
    """
    Return expanded file path.
    If filename is relative it is relative to default_dir.
    Expand %(project_dir) and %(dist_dir) in filename.
    """
    result = filename % {
            'project_dir': OPTIONS.project_dir,
            'dist_dir': OPTIONS.dist_dir}
    if not os.path.isabs(result):
         result = os.path.join(default_dir, result)
    return os.path.normpath(result)

def rename_dist_file(src, dst):
    """
    Rename file in distribution directory.
    If src or dst are relative they are relative to DIST_DIR.
    src and dst expand %(project_dir) and %(dist_dir).
    Honors --dry-run and --verbose command=line options.
    """
    src = expand_path(src, OPTIONS.dist_dir)
    dst = expand_path(dst, OPTIONS.dist_dir)
    verbose('mv %s %s' % (src, dst))
    if not OPTIONS.dry_run:
        os.rename(src, dst)

def copy_dist_files(src, dst):
    """
    Copy src files (wildcards allowed) to dst.
    If single src file dst can be an existing directory else file name assumed.
    If multiple src files dst is directory path.
    Missing directories will be created if they don't exist.
    If src is relative it is relative to PROJECT_DIR.
    If dst is relative it is relative to DIST_DIR.
    src and dst expand %(project_dir) and %(dist_dir).
    Honors --dry-run and --verbose command=line options.
    Error exit if there are no source files to copy.
    """
    src = expand_path(src, OPTIONS.project_dir)
    dst = expand_path(dst, OPTIONS.dist_dir)
    filenames = glob.glob(src)
    count = 0
    if len(filenames) > 1 or os.path.isdir(dst):
        if not os.path.isdir(dst):
            verbose('mkdir -p %s' % dst)
            if not OPTIONS.dry_run:
                os.makedirs(dst)
        for f in filenames:
            g = os.path.join(dst, os.path.basename(f))
            verbose('cp %s %s' % (f, g))
            if not OPTIONS.dry_run:
                shutil.copyfile(f, g)
            count += 1
    else:
        dst_dir = os.path.dirname(dst)
        if not os.path.isdir(dst_dir):
            verbose('mkdir -p %s' % dst_dir)
            if not OPTIONS.dry_run:
                os.makedirs(dst_dir)
        verbose('cp %s %s' % (src, dst))
        if not OPTIONS.dry_run:
            shutil.copyfile(src, dst)
        count += 1
    if count == 0:
        die('missing source files: %s' % src)


####################
# Application code #
####################

def copy_dist(src_dir,
              dst_dir,
              src_copy_files=[],    # Match list of source files to copy.
              dst_keep_files=[],    # Match list of destination files to keep.
             ):
    """
    Copy files matching the src_copy_files match list from src_dir to dst_dir
    directory.

    Prior to copying clear dst_dir but don't delete paths matching the
    dst_keep_files match list.

    Source directory and file names starting with . are implicitly excluded.
    Symlinks in source directory (UNIX only) are skipped.

    If the --compile command-line option is set compile Python files and remove
    .py files from destination.

    """
    src_dir = os.path.abspath(src_dir)
    dst_dir = os.path.abspath(dst_dir)
    src_copy_files = src_copy_files + ['!.*', '!*/.*', '!*.pyc', '!*.pyo']

    # Remove existing destination files (unless they are kept).
    # Walk from bottom to ensure directories are empty prior to removal.
    infomsg('deleting files from %s' % dst_dir)
    for dirpath, dirnames, filenames in os.walk(dst_dir, topdown=False):
        for filename in filenames:
            filename = os.path.join(dirpath, filename)
            if not matches(filename, dst_keep_files, dst_dir):
                verbose('rm %s' % filename)
                if not OPTIONS.dry_run:
                    os.remove(filename)
        for dirname in dirnames:
            dirname = os.path.join(dirpath, dirname)
            # Remove empty directories unless explicitly kept.
            if len(os.listdir(dirname)) == 0 \
            and not matches(dirname, dst_keep_files, dst_dir):
                if os.path.islink(dirname):
                    verbose('rm symlink %s' % dirname)
                    if not OPTIONS.dry_run:
                        os.remove(dirname)
                else:
                    verbose('rmdir %s' % dirname)
                    if not OPTIONS.dry_run:
                        os.rmdir(dirname)
    # Copy source files to destination.
    infomsg('copying files from %s to %s' % (src_dir, dst_dir))
    if not os.path.isdir(dst_dir):
        verbose('mkdir %s' % dst_dir)
        if not OPTIONS.dry_run:
            os.mkdir(dst_dir)
    for dirpath, dirnames, filenames in os.walk(src_dir):
        for filename in filenames:
            filename = os.path.join(dirpath, filename)
            if matches(filename, src_copy_files, src_dir):
                dst_dirname = dst_path(os.path.dirname(filename),
                                       src_dir, dst_dir)
                if not os.path.isdir(dst_dirname):
                    verbose('mkdir %s' % dst_dirname)
                    if not OPTIONS.dry_run:
                        os.makedirs(dst_dirname)
                dst_filename = dst_path(filename, src_dir, dst_dir)
                verbose('cp %s %s' % (filename, dst_filename))
                if not OPTIONS.dry_run:
                    shutil.copy(filename, dst_filename)
    # Compile destination source files and then delete them.
    if OPTIONS.compile:
        infomsg('compiling files in %s' % dst_dir)
        for dirpath, dirnames, filenames in os.walk(dst_dir):
            for filename in filenames:
                filename = os.path.join(dirpath, filename)
                if not matches(filename, dst_keep_files, dst_dir):
                    if fnmatch.fnmatch(filename, '*.py'):
                        verbose('compiling %s' % filename)
                        if not OPTIONS.dry_run:
                            py_compile.compile(filename, doraise=True)
                        verbose('rm %s' % filename)
                        if not OPTIONS.dry_run:
                            os.remove(filename)

class Manifest(object):
    """
    Read/write/compare MANIFEST file with distribution files.
    """

    def __init__(self, dist_dir):
        self.dist_dir = os.path.abspath(dist_dir)
        self.manifest_file = os.path.join(self.dist_dir, 'MANIFEST')


    def _read_write(self, mode, files=None):
        """
        Read (mode = 'r') or write (mode = 'w') files list to/from MANIFEST
        file.
        """
        f = open(self.manifest_file, mode)
        try:
            if mode == 'w':
                files = ['%s\n' % filename for filename in files]
                f.writelines(files)
            else:
                files = f.readlines()
                return [filename.strip() for filename in files] # Strip \n.
        finally:
            f.close()

    def dist_files(self):
        """
        Read relative names of files in distribution directory and return in
        list. Path name separators normalized to UNIX.
        """
        result = []
        for dirpath, dirnames, filenames in os.walk(self.dist_dir):
            for filename in filenames:
                filename = os.path.join(dirpath, filename)
                filename = filename[len(self.dist_dir)+1:]
                if sys.platform == 'win32':
                    filename = filename.replace(os.sep, '/')
                result.append(filename)
        return result

    def read(self):
        """
        Return list of file names from MANIFEST file.
        """
        return self._read_write('r')

    def write(self):
        """
        Write MANIFEST file containing relative names of all files in the
        distribution directory.
        """
        infomsg('writing manifest: %s' % self.manifest_file)
        self._read_write('w', self.dist_files())

    def compare(self):
        """
        Compare the files in the MANIFEST with the files in the distribution
        directory and print any differences.
        Returns False if no MANIFEST or there are differences.
        """
        if not os.path.isfile(self.manifest_file):
            return False
        infomsg('comparing manifest: %s' % self.manifest_file)
        dist_files = set(self.dist_files())
        dist_files.discard('MANIFEST')
        manifest_files = set(self.read())
        manifest_files.discard('MANIFEST')
        result = True
        diff = [i for i in manifest_files.difference(dist_files)]
        diff.sort()
        for filename in diff:
            errmsg('-' + filename)  # File in manifest but not in distribution.
            result = False
        diff = [i for i in dist_files.difference(manifest_files)]
        diff.sort()
        for filename in diff:
            errmsg('+' + filename)  # File in distribution but not in manifest.
            result = False
        return result

def build_project_runtime():
    """
    Copy all project files to distribution directory.
    Don't copy distribution directory and don't overwrite Django or Python
    runtimes.
    """
    copy_dist(OPTIONS.project_dir, OPTIONS.dist_dir,
              src_copy_files = PROJECT_COPY_FILES +
                  ['!' + os.path.abspath(os.path.join(OPTIONS.dist_dir, '*'))],
              dst_keep_files = [os.path.join(d, '*')
                  for d in (PYTHON_RUNTIME_DIR, DJANGO_RUNTIME_DIR)] +
                  [Manifest(OPTIONS.dist_dir).manifest_file],
              )

def build_django_runtime():
    copy_dist(DJANGO_DIR,
              os.path.join(OPTIONS.dist_dir, DJANGO_RUNTIME_DIR),
              src_copy_files = DJANGO_COPY_FILES,
              )

def build_python_runtime():
    dst_dir = os.path.abspath(
              os.path.join(OPTIONS.dist_dir, PYTHON_RUNTIME_DIR))
    copy_dist(PYTHON_DIR,
              dst_dir,
              src_copy_files = PYTHON_COPY_FILES,
              )
    for filename in PYTHON_SYSTEM_FILES:
        filename = os.path.abspath(filename)
        verbose('cp %s %s' % (filename, dst_dir))
        if not OPTIONS.dry_run:
            shutil.copy(filename, dst_dir)

def exec_inno_setup(iss_file):
    infomsg('compiling setup script %s' % iss_file)
    if not OPTIONS.dry_run:
        args = [INNO_SETUP_COMPILER, '/Q', iss_file]
        if OPTIONS.verbose:
            del args[1] # Delete quiet option.
        subprocess.check_call(args)

TARBALL_FILE_RE = r'^(.+)\.((tar\.gz)|(tgz)|(tar\.bz2))$'

def make_tarball(filename):
    """
    Make a tarball containing files in the distribution directory.
    The stored file root directory is the filename base.
    """
    # Strip directory name and tarball extensions from file name.
    basename = os.path.basename(filename)
    basename = re.match(TARBALL_FILE_RE, basename).group(1)
    # Get list of file in distribution directory excluding the manifest file.
    dist_files = Manifest(OPTIONS.dist_dir).dist_files()
    try:
        dist_files.remove('MANIFEST')
    except ValueError:
        pass
    infomsg('creating tarball: %s' % filename)
    if not OPTIONS.dry_run:
        if filename.endswith('.bz2'):
            mode = 'w:bz2'
        else:
            mode = 'w:gz'
        tar = tarfile.open(filename, mode)
    for distfile in dist_files:
        name = os.path.join(OPTIONS.dist_dir, distfile)
        arname = '%s/%s' % (basename, distfile)
        verbose('archiving: %s' % arname)
        if not OPTIONS.dry_run:
            tarinfo = tar.gettarinfo(name, arname)
            tarinfo.uid = 0
            tarinfo.gid = 0
            tarinfo.uname = 'root'
            tarinfo.gname = 'root'
            tar.addfile(tarinfo, file(name, 'rb'))
    if not OPTIONS.dry_run:
        tar.close()


if __name__ == "__main__":
    description = """Build a self contained Win32 distribution for the Django
project in the PROJECT_DIR. Optionally build Python and Django runtimes.
Distribution files are written to DIST_DIR directory (default 'PROJECT_DIR/%s').
Python runtime written to 'DIST_DIR/%s'.
Django runtime written to 'DIST_DIR/%s'.""" % \
(DIST_DIR, PYTHON_RUNTIME_DIR, DJANGO_RUNTIME_DIR)

    from optparse import OptionParser
    parser = OptionParser(usage='usage: %prog [OPTIONS] PROJECT_DIR',
        version='%prog ' + VERSION,
        description=description)
    parser.add_option('-d', '--dist-dir',
        dest='dist_dir', default=None, metavar='DIST_DIR',
        help='distribution destination directory')
    parser.add_option('-f', '--conf-file',
        dest='conf_file', default=None, metavar='CONF_FILE',
        help='configuration file')
    parser.add_option('-p', '--python-runtime',
        action='store_true', dest='python_runtime', default=False,
        help='copy a Python runtime from PYTHON_DIR')
    parser.add_option('-j', '--django-runtime',
        action='store_true', dest='django_runtime', default=False,
        help='copy a Django runtime from DJANGO_DIR')
    parser.add_option('-c', '--compile',
        action='store_true', dest='compile', default=False,
        help='distribute compiled .pyc files')
    parser.add_option('-i', '--iss-file',
        dest='iss_file', default=None, metavar='ISS_FILE',
        help='create install wizard using Inno Setup compiler')
    parser.add_option('-t', '--tarball',
        dest='tarball', default=None, metavar='TARBALL_FILE',
        help='create TARBALL_FILE of distribution directory')
    parser.add_option('-m', '--manifest',
        action='store_true', dest='manifest', default=False,
        help='write MANIFEST file and exit')
    parser.add_option('-C', '--check-manifest',
        action='store_true', dest='check_manifest', default=False,
        help='check distribution against MANIFEST file and exit')
    parser.add_option('-n', '--dry-run',
        action='store_true', dest='dry_run', default=False,
        help='show what would have been done')
    parser.add_option('-v', '--verbose',
        action='store_true', dest='verbose', default=False,
        help='increase verbosity')
    if len(sys.argv) == 1:
        parser.parse_args(['--help'])
    OPTIONS, args = parser.parse_args()
    # Validate PROJECT_DIR argument.
    if len(args) != 1:
        die('too few or too many arguments')
    project_dir = args[0]
    if not os.path.isdir(project_dir):
        die('PROJECT_DIR not found: %s' % project_dir)
    project_dir = os.path.abspath(project_dir)
    OPTIONS.__dict__['project_dir'] = project_dir
    # Read configuration file.
    if OPTIONS.conf_file is not None:
        if not os.path.isfile(OPTIONS.conf_file):
            die('configuration file not found: %s' % OPTIONS.conf_file)
        load_conf(OPTIONS.conf_file)
    else:
        # If conf file exists in project directory load it.
        conf_file = os.path.join(project_dir, CONF_FILE)
        if os.path.isfile(conf_file):
            load_conf(conf_file)
    # Validate command options.
    if OPTIONS.tarball is not None:
        tarball = OPTIONS.tarball
        if tarball == '-':  # Use conf value.
            tarball = TARBALL_FILE
            if tarball is None:
                die('TARBALL_FILE default is None')
            if not os.path.isabs(tarball):
                tarball = os.path.join(project_dir, tarball)
        tarball = os.path.normpath(tarball)
        if not os.path.isdir(os.path.dirname(tarball)):
            die('missing tarball directory: %s' % os.path.dirname(tarball))
        if not re.match(TARBALL_FILE_RE, tarball):
            die('illegal tarball file name extension: %s' % tarball)
        OPTIONS.__dict__['tarball'] = tarball
    if OPTIONS.iss_file is not None:
        if sys.platform != 'win32':
            die('Inno setup compiler requires win32 platform')
        if not os.path.isfile(INNO_SETUP_COMPILER):
            die('Inno Setup compiler not found: %s' % INNO_SETUP_COMPILER)
        iss_file = OPTIONS.iss_file
        if iss_file == '-':  # Use conf value.
            iss_file = ISS_FILE
            if iss_file is None:
                die('ISS_FILE default is None')
            if not os.path.isabs(iss_file):
                iss_file = os.path.join(project_dir, iss_file)
        iss_file = os.path.normpath(iss_file)
        if not os.path.isfile(iss_file):
            die('Inno Setup script not found: %s' % iss_file)
        OPTIONS.__dict__['iss_file'] = iss_file
    if OPTIONS.dist_dir is None:
        OPTIONS.__dict__['dist_dir'] = os.path.join(project_dir, DIST_DIR)
    if OPTIONS.django_runtime:
        if not os.path.isabs(DJANGO_DIR):
            DJANGO_DIR = os.path.join(project_dir, DJANGO_DIR)
        if not os.path.isdir(DJANGO_DIR):
            die('DJANGO_DIR not found: %s' % DJANGO_DIR)
    if OPTIONS.python_runtime:
        if not os.path.isabs(PYTHON_DIR):
            PYTHON_DIR = os.path.join(project_dir, PYTHON_DIR)
        if not os.path.isdir(PYTHON_DIR):
            die('PYTHON_DIR not found: %s' % PYTHON_DIR)
    # Do the work.
    if OPTIONS.manifest:
        Manifest(OPTIONS.dist_dir).write()
        sys.exit()
    manifest = Manifest(OPTIONS.dist_dir)
    if OPTIONS.check_manifest:
        if not os.path.isfile(manifest.manifest_file):
            die('missing MANIFEST file: %s' % manifest.manifest_file)
        if not manifest.compare():
            sys.exit(2)
        sys.exit()
    infomsg('executing pre_build')
    pre_build()
    build_project_runtime()
    if OPTIONS.django_runtime:
        build_django_runtime()
    if OPTIONS.python_runtime:
        build_python_runtime()
    infomsg('executing post_build')
    post_build()
    if os.path.isfile(manifest.manifest_file):
        if OPTIONS.dry_run:
            infomsg('dry run: skipping manifest comparision')
        elif not manifest.compare():
            die('MANIFEST file differences')
    if OPTIONS.iss_file is not None:
        exec_inno_setup(OPTIONS.iss_file)
    if OPTIONS.tarball is not None:
        make_tarball(OPTIONS.tarball)
