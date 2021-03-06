import sys
import os.path
import webbrowser
import tempfile
import tarfile
import shutil

import urllib2
import json
import pprint
import StringIO
from ConfigParser import SafeConfigParser
from argparse import ArgumentParser
from subprocess import call, check_call, STDOUT
import fnmatch

from ordereddict import OrderedDict

from setuptools import find_packages
from pkg_resources import WorkingSet, Requirement, resource_stream

from openmdao.main.factorymanager import get_available_types, plugin_groups
from openmdao.util.fileutil import build_directory, find_files, get_ancestor_dir
from openmdao.util.dep import PythonSourceTreeAnalyser
from openmdao.util.dumpdistmeta import get_metadata
from openmdao.util.git import download_github_tar
from openmdao.util.view_docs import view_docs
from openmdao.main.pkg_res_factory import plugin_groups
from openmdao.main import __version__

#from sphinx.setup_command import BuildDoc
import sphinx


def _load_templates():
    ''' Reads templates from files in the plugin_templates directory.
    
    conf.py:
      This is the template for the file that Sphinx uses to configure itself.
      It's intended to match the conf.py for the OpenMDAO docs, so if those 
      change, this may need to be updated.
    
    index.rst
      template for the top level file in the Sphinx docs for the plugin
      
    usage.rst
      template for the file where the user may add specific usage documentation
      for the plugin
      
    setup.py
      template for the file that packages and install the plugin using
      setuptools
      
    MANIFEST.in
      template for the file that tells setuptools/distutils what extra data
      files to include in the distribution for the plugin
      
    README.txt
      template for the README.txt file.
      
    setup.cfg
      template for the setup configuration file, where all of the user
      supplied metadata is located.  This file may be hand edited by the 
      plugin developer.

    '''
    
    # There are a number of string templates that are used to produce various
    # files within the plugin distribution. These templates are stored in the
    # templates dict, with the key being the name of the file that the 
    # template corresponds to.
    templates = {}
    
    for item in ['index.rst', 'usage.rst', 'MANIFEST.in',
                 'README.txt', 'setup.cfg']:
    
        infile = resource_stream(__name__, 
                                 os.path.join('plugin_templates', item))
            
        templates[item] = infile.read()
        infile.close()
    
    infile = resource_stream(__name__, 
                             os.path.join('plugin_templates', 'setup_py_template'))
            
    templates['setup.py'] = infile.read()
    infile.close()
    
    infile = resource_stream(__name__, 
                             os.path.join('plugin_templates', 'conf_py_template'))
            
    templates['conf.py'] = infile.read()
    infile.close()
    
    # This dict contains string templates corresponding to skeleton python
    # source files for each of the recognized plugin types.  
    
    # TODO: These should be updated to reflect best practices because most
    # plugin developers will start with these when they create new plugins.
    class_templates = {}
    
    for item in ['openmdao.component', 'openmdao.driver', 'openmdao.variable',
                 'openmdao.surrogatemodel']:
    
        infile = resource_stream(__name__, 
                                 os.path.join('plugin_templates', item))
            
        class_templates[item] = infile.read()
        infile.close()
        
        
    infile = resource_stream(__name__, 
                             os.path.join('plugin_templates','test_template'))
        
    test_template = infile.read()
    infile.close()
    
    return templates, class_templates, test_template
    

def _get_srcdocs(destdir, name):
    """ Return RST for source docs. """
    startdir = os.getcwd()
    srcdir = os.path.join(destdir,'src')
    if os.path.exists(srcdir):
        os.chdir(srcdir)
        try:
            srcmods = _get_src_modules('.')
        finally:
            os.chdir(startdir)
    else:
        srcmods = ["%s.%s" % (name, name)]

    contents = [
        """
.. _%s_src_label:


====================
Source Documentation
====================
        
        """ % name
        ]
    
    for mod in sorted(srcmods):
        pkgfile = '%s.py' % mod
        pkg, dot, name = mod.rpartition('.')
        pyfile = '%s.py' % name
        underline = '-'*len(pyfile)
        contents.append("""
.. index:: %s

.. _%s:

%s
%s

.. automodule:: %s
   :members:
   :undoc-members:
   :show-inheritance:
    
        """ % (pyfile, pkgfile, pyfile, underline, mod))

    return ''.join(contents)


def _get_pkgdocs(cfg):
    """Return a string in reST format that contains the metadata
    for the package.
    
    cfg: ConfigParser
        ConfigParser object used to read the setup.cfg file
    """
    lines = ['\n',
             '================\n',
             'Package Metadata\n',
             '================\n',
             '\n']

    metadata = {}
    if cfg.has_section('metadata'):
        metadata.update(dict([item for item in cfg.items('metadata')]))
    if cfg.has_section('openmdao'):
        metadata.update(dict([item for item in cfg.items('openmdao')]))

    tuplist = list(metadata.items())
    tuplist.sort()
    for key,value in tuplist:
        if value.strip():
            if '\n' in value:
                lines.append("- **%s**:: \n\n" % key)
                for v in [vv.strip() for vv in value.split('\n')]:
                    if v:
                        lines.append("    %s\n" % v)
                lines.append('\n')
            elif value != 'UNKNOWN':
                lines.append("- **%s:** %s\n\n" % (key, value))
        
    return ''.join(lines)


def _get_setup_options(distdir, metadata):
    """ Return dictionary of setup options. """
    # a set of names of variables that are supposed to be lists
    lists = set([
        'keywords',
        'install_requires',
        'packages',
        'classifiers',
        ])
    
    # mapping of new metadata names to old ones
    mapping = {
        'name': 'name',
        'version': 'version',
        'keywords': 'keywords',
        'summary': 'description',
        'description': 'long_description',
        'home-page': 'url',
        'download-url': 'download_url',
        'author': 'author',
        'author-email': 'author_email',
        'maintainer': 'maintainer',
        'maintainer-email': 'maintainer_email',
        'license': 'license',
        'classifier': 'classifiers',
        'requires-dist': 'install_requires',
        'entry_points': 'entry_points',
        #'py_modules': 'py_modules',
        'packages': 'packages',
        }
    
    # populate the package data with sphinx docs
    # we have to list all of the files because setuptools doesn't
    # handle nested directories very well
    pkgdir = os.path.join(distdir, 'src', metadata['name'])
    plen = len(pkgdir)+1
    sphinxdir = os.path.join(pkgdir, 'sphinx_build', 'html')
    testdir = os.path.join(pkgdir, 'test')
    pkglist = list(find_files(sphinxdir))
    pkglist.extend(list(find_files(testdir, exclude="*.py[co]")))
    pkglist = [p[plen:] for p in pkglist]
    setup_options = {
        #'packages': [metadata['name']],
        'package_data': { 
            metadata['name']: pkglist #[
            #'sphinx_build/html/*.*',
            #'sphinx_build/html/_modules/*',
            #'sphinx_build/html/_sources/*',
            #'sphinx_build/html/_static/*',
            #] 
        },
        'package_dir': {'': 'src'},
        'zip_safe': False,
        'include_package_data': True,
    }
    
    for key,val in metadata.items():
        if key in mapping:
            if isinstance(val, basestring):
                if mapping[key] in lists:
                    val = [p.strip() for p in val.split('\n') if p.strip()]
                else:
                    val = val.strip()
            setup_options[mapping[key]] = val

    return setup_options


def _pretty(obj):
    """ Return pretty-printed `obj`. """
    sio = StringIO.StringIO()
    pprint.pprint(obj, sio)
    return sio.getvalue()


def _get_py_files(distdir):
    def _pred(fname):
        parts = fname.split(os.sep)
        if parts[-1] in ['setup.py', '__init__.py'] or 'test' in parts:
            return False
        return fname.endswith('.py')
    return list(find_files(distdir, _pred))
        

def _get_src_modules(topdir):
    topdir = os.path.abspath(os.path.expandvars(os.path.expanduser(topdir)))
    pyfiles = _get_py_files(topdir)
    noexts = [os.path.splitext(f)[0] for f in pyfiles]
    rel = [f[len(topdir)+1:] for f in noexts]
    return ['.'.join(f.split(os.sep)) for f in rel]
    

def _get_template_options(distdir, cfg, **kwargs):
    """ Return dictionary of options for template substitution. """
    if cfg.has_section('metadata'):
        metadata = dict([item for item in cfg.items('metadata')])
    else:
        metadata = {}
    if cfg.has_section('openmdao'):
        openmdao_metadata = dict([item for item in cfg.items('openmdao')])
    else:
        openmdao_metadata = {}
        
    if 'static_path' not in openmdao_metadata:
        openmdao_metadata['static_path'] = ''

    if 'packages' in kwargs:
        metadata['packages'] = kwargs['packages']
    else:
        metadata['packages'] = [metadata['name']]

    setup_options = _get_setup_options(distdir, metadata)
    
    template_options = {
        'copyright': '',
        'summary': '',
        'setup_options': _pretty(setup_options)
    }
    
    template_options.update(setup_options)
    template_options.update(openmdao_metadata)
    template_options.update(kwargs)
    
    name = template_options['name']
    version = template_options['version']
    
    template_options.setdefault('release', version)
    template_options.setdefault('title_marker', 
                                '='*(len(name)+len(' Documentation')))
        
    return template_options


def plugin_quickstart(parser, options, args=None):
    """A command line script (plugin quickstart) points to this.  It generates a
    directory structure for an openmdao plugin package along with Sphinx docs.
    
    usage: plugin quickstart <dist_name> [-v <version>] [-d <dest_dir>] [-g <plugin_group>] [-c class_name]
    
    """
    if args:
        print_sub_help(parser, 'quickstart')
        return -1

    name = options.dist_name
    if options.classname:
        classname = options.classname
    else:
        classname = "%s%s" % ((name.upper())[0], name[1:])
    version = options.version
    
    options.dest = os.path.abspath(os.path.expandvars(os.path.expanduser(options.dest)))
    if not options.group.startswith('openmdao.'):
        options.group = 'openmdao.'+options.group
        
    templates, class_templates, test_template = _load_templates()

    startdir = os.getcwd()
    try:
        os.chdir(options.dest)
        
        if os.path.exists(name):
            raise OSError("Can't create directory '%s' because it already"
                          " exists." % os.path.join(options.dest, name))
        
        cfg = SafeConfigParser(dict_type=OrderedDict)
        stream = StringIO.StringIO(templates['setup.cfg'] % { 'name':name, 
                                                              'version':version })
        cfg.readfp(stream, 'setup.cfg')
        cfgcontents = StringIO.StringIO()
        cfg.write(cfgcontents)
        
        template_options = \
            _get_template_options(os.path.join(options.dest, name),
                                  cfg, classname=classname)
        
        template_options['srcmod'] = name
    
        dirstruct = {
            name: {
                'setup.py': templates['setup.py'] % template_options,
                'setup.cfg': cfgcontents.getvalue(),
                'MANIFEST.in': templates['MANIFEST.in'] % template_options,
                'README.txt': templates['README.txt'] % template_options,
                'src': {
                    name: {
                        '__init__.py': '', #'from %s import %s\n' % (name,classname),
                        '%s.py' % name: class_templates[options.group] % template_options,
                        'test': {
                                'test_%s.py' % name: test_template % template_options
                            },
                        },
                    },
                'docs': {
                    'conf.py': templates['conf.py'] % template_options,
                    'index.rst': templates['index.rst'] % template_options,
                    'srcdocs.rst': _get_srcdocs(options.dest, name),
                    'pkgdocs.rst': _get_pkgdocs(cfg),
                    'usage.rst': templates['usage.rst'] % template_options,
                    },
            },
        }

        build_directory(dirstruct)
    
    finally:
        os.chdir(startdir)

    return 0

        
def _verify_dist_dir(dpath):
    """Try to make sure that the directory we've been pointed to actually
    contains a distribution.
    """
    if not os.path.isdir(dpath):
        raise IOError("directory '%s' does not exist" % dpath)
    
    expected = ['src', 'docs', 'setup.py', 'setup.cfg', 'MANIFEST.in',
                os.path.join('docs','conf.py'),
                os.path.join('docs','index.rst'),
                os.path.join('docs','srcdocs.rst')]
    for fname in expected:
        if not os.path.exists(os.path.join(dpath, fname)):
            raise IOError("directory '%s' does not contain '%s'" %
                          (dpath, fname))


_EXCL_SET = set(['test', 'docs', 'sphinx_build', '_downloads'])
def _exclude_funct(path):
    return len(_EXCL_SET.intersection(path.split(os.sep))) > 0


#
# FIXME: this still needs some work, but for testing purposes it's ok for now
#
def _find_all_plugins(searchdir):
    """Return a dict containing lists of each plugin type found, keyed by
    plugin group name, e.g., openmdao.component, openmdao.variable, etc.
    """
    dct = {}
    modnames = ['openmdao.main', 
                'openmdao.lib.datatypes', 
                'openmdao.lib.components',
                'openmdao.lib.drivers',
                'openmdao.lib.surrogatemodels',
                'openmdao.lib.doegenerators',
                'openmdao.lib.differentiators',
                'openmdao.lib.optproblems',
                'openmdao.lib.casehandlers',
                'openmdao.lib.architectures']
    
    modules = []
    for mod in modnames:
        try:
            __import__(mod)
        except ImportError:
            print 'skipping import of %s' % mod
        else:
            modules.append(sys.modules[mod])
            
    dirs = [os.path.dirname(m.__file__) for m in modules]+[searchdir]
    psta = PythonSourceTreeAnalyser(dirs, exclude=_exclude_funct)
    
    for key, val in plugin_groups.items():
        dct[key] = set(psta.find_inheritors(val))

    return dct


def _get_entry_points(startdir):
    """ Return formatted list of entry points. """
    plugins = _find_all_plugins(startdir)
    entrypoints = StringIO.StringIO()
    for key,val in plugins.items():
        epts = []
        for v in val:
            if v.startswith('openmdao.'):
                continue
            mod,cname = v.rsplit('.', 1)
            epts.append('%s.%s=%s:%s' % (mod, cname, mod, cname))
        if epts:
            entrypoints.write("\n[%s]\n" % key)
            for ept in epts:
                entrypoints.write("%s\n" % ept)
    
    return entrypoints.getvalue()


def plugin_makedist(parser, options, args=None, capture=None):
    """A command line script (plugin makedist) points to this.  It creates a 
    source distribution containing Sphinx documentation for the specified
    distribution directory.  If no directory is specified, the current directory
    is assumed.
    
    usage: plugin makedist [dist_dir_path]
    
    """
    if args is not None and len(args) > 1:
        print_sub_help(parser, 'makedist')
        return -1

    if args:
        dist_dir = args[0]
    else:
        dist_dir = '.'
    dist_dir = os.path.abspath(os.path.expandvars(os.path.expanduser(dist_dir)))
    _verify_dist_dir(dist_dir)

    startdir = os.getcwd()
    os.chdir(dist_dir)

    templates, class_templates, test_template = _load_templates()

    try:
        plugin_build_docs(parser, options)
        
        cfg = SafeConfigParser(dict_type=OrderedDict)
        cfg.readfp(open('setup.cfg', 'r'), 'setup.cfg')
            
        print "collecting entry point information..."
        cfg.set('metadata', 'entry_points', _get_entry_points('src'))
        
        template_options = _get_template_options(options.dist_dir_path, cfg,
                                                 packages=find_packages('src'))

        dirstruct = {
            'setup.py': templates['setup.py'] % template_options,
            }
        
        name = cfg.get('metadata', 'name')
        version = cfg.get('metadata', 'version')
        
        if sys.platform == 'win32':  # pragma no cover
            disttar = "%s-%s.zip" % (name, version)
        else:
            disttar = "%s-%s.tar.gz" % (name, version)
        disttarpath = os.path.join(startdir, disttar)
        if os.path.exists(disttarpath):
            sys.stderr.write("ERROR: distribution %s already exists.\n"
                             % disttarpath)
            return -1
        
        build_directory(dirstruct, force=True)

        cmdargs = [sys.executable, 'setup.py', 'sdist', '-d', startdir]
        if capture:
            stdout = open(capture, 'w')
            stderr = STDOUT
        else:  # pragma no cover
            stdout = None
            stderr = None
        try:
            retcode = call(cmdargs, stdout=stdout, stderr=stderr)
        finally:
            if stdout is not None:
                stdout.close()
        if retcode:
            cmd = ' '.join(cmdargs)
            sys.stderr.write("\nERROR: command '%s' returned error code: %s\n"
                             % (cmd, retcode))
            return retcode
    finally:
        os.chdir(startdir)

    if os.path.exists(disttar):
        print "Created distribution %s" % disttar
        return 0
    else:
        sys.stderr.write("\nERROR: failed to make distribution %s" % disttar)
        return -1


# This brings up a browser window which can be a problem during testing.
def plugin_docs(parser, options, args=None):  # pragma no cover
    """A command line script (plugin docs) points to this. It brings up
    the Sphinx documentation for the named plugin in a browser.
    """
    if args:
        print_sub_help(parser, 'docs')
        return -1
    
    if options.plugin_dist_name is None:
        view_docs(options.browser)
    else:
        url = _plugin_docs(options.plugin_dist_name)
        wb = webbrowser.get(options.browser)
        wb.open(url)


def _plugin_docs(plugin_name):
    """Returns a url for the Sphinx docs for the named plugin.
    The plugin must be importable in the current environment.
    
    plugin_name: str
        Name of the plugin distribution, module, or class.
    """
    parts = plugin_name.split('.')
    
    if len(parts) == 1: # assume it's a class name and try to find unambiguous module
        modname = None
        # loop over available types to find a class name that matches
        for name, version in get_available_types():
            mname, cname = name.rsplit('.', 1)
            if cname == plugin_name:
                if modname and modname != mname:
                    raise RuntimeError("Can't determine module for class '%s'"
                                       " unambiguously. found in %s"
                                       % (cname, [mname, modname]))
                modname = mname
                parts = modname.split('.')
   
        if modname is None: # didn't find a class, so assume plugin_name is a dist name
            parts = [plugin_name, plugin_name]
        
    for i in range(len(parts)-1):
        mname = '.'.join(parts[:len(parts)-i])
        try:
            __import__(mname)
            mod = sys.modules[mname]
            modname = mname
            break
        except ImportError:
            pass
    else:
        # Possibly something in contrib that's a directory.
        try:
            __import__(plugin_name)
            mod = sys.modules[plugin_name]
            modname = plugin_name
        except ImportError:
            raise RuntimeError("Can't locate package/module '%s'" % plugin_name)
    
    if modname.startswith('openmdao.'): # lookup in builtin docs
        fparts = mod.__file__.split(os.sep)
        pkg = '.'.join(modname.split('.')[:2])
        anchorpath = '/'.join(['srcdocs', 'packages',
                               '%s.html#module-%s' % (pkg, modname)])
        if any([p.endswith('.egg') and p.startswith('openmdao.') for p in fparts]): 
            # this is a release version, so use online docs
            url = '/'.join(['http://openmdao.org/releases/%s/docs'
                            % __version__, anchorpath])
        else:  # it's a developer version, so use locally built docs
            htmldir = os.path.join(get_ancestor_dir(sys.executable, 3), 'docs', 
                                   '_build', 'html')
            if not os.path.isfile(os.path.join(htmldir, 'index.html')):
                #make sure the local docs are built
                print "local docs not found.\nbuilding them now...\n"
                check_call(['openmdao', 'build_docs'])
            url = 'file://'+os.path.join(htmldir, anchorpath)
            url = url.replace('\\', '/')
    else:
        url = os.path.join(os.path.dirname(os.path.abspath(mod.__file__)),
                           'sphinx_build', 'html', 'index.html')
    return url 


def plugin_install(parser, options, args=None, capture=None):
    """A command line script (plugin install) points to this. It installs
    the specified plugin distribution into the current environment.
    
    """ 
    if args:
        print_sub_help(parser, 'install')
        return -1

    # Interact with github (but not when testing).
    if options.github or options.all:  # pragma no cover
        plugin_url = 'https://api.github.com/orgs/OpenMDAO-Plugins/repos?type=public'
        github_plugins = []
        
        if options.all:
            #go get names of all the github plugins
            plugin_page = urllib2.urlopen(plugin_url)
            for line in plugin_page.fp:
                text = json.loads(line)
                for item in sorted(text):
                    github_plugins.append(item['name'])
           
        else:
            #just use the name of the specific plugin requested
            github_plugins.append(options.dist_name)
        
        for plugin in github_plugins:
            try:
                print "Installing plugin:", plugin
                _github_install(plugin, options.findlinks)
            except:
                pass
        
    else: # Install plugin from local file or directory
        develop = False
        if not options.dist_name:
            print "installing distribution from current directory as a 'develop' egg"
            develop = True
        
        if develop:
            cmdargs = [sys.executable, 'setup.py', 'develop', '-N']
        else:
            cmdargs = ['easy_install', '-f', options.findlinks, options.dist_name]
            
        cmd = ' '.join(cmdargs)
        if capture:
            stdout = open(capture, 'w')
            stderr = STDOUT
        else:  # pragma no cover
            stdout = None
            stderr = None
        try:
            retcode = call(cmdargs, stdout=stdout, stderr=stderr)
        finally:
            if stdout is not None:
                stdout.close()
        if retcode:
            sys.stderr.write("\nERROR: command '%s' returned error code: %s\n"
                             % (cmd,retcode))
            return -1
            
    if not sys.platform.startswith('win'):
        # make sure LD_LIBRARY_PATH is updated if necessary in activate script
        update_libpath(options)
    
    return 0

def _github_install(dist_name, findLinks):
    # Get plugin from github.
    #FIXME: this should support all valid version syntax (>=, <=, etc.)
    pieces = dist_name.split('==')
    name = pieces[0]
    
    # User specified version using easy_install style ("plugin==version")
    if len(pieces) > 1:
        version = pieces[1]
        
    # Get most recent version from our tag list
    else:
        url = 'https://api.github.com/repos/OpenMDAO-Plugins/%s/tags' % name
        try:
            resp = urllib2.urlopen(url)
        except urllib2.HTTPError:
            print "\nERROR: plugin named '%s' not found in OpenMDAO-Plugins" % name
            return -1
            
        for line in resp.fp:
            text = json.loads(line)

            tags = []
            for item in text:
                tags.append(item['name'])
        try:
            tags.sort(key=lambda s: map(int, s.split('.')))
        except ValueError:
            print "\nERROR: the releases for the plugin named '%s' have" \
                  " not been tagged correctly for installation." % name
            print "You may want to contact the repository owner"
            return -1
            
        if not tags:
            print "\nERROR: plugin named '%s' has no tagged releases." % name
            print "You may want to contact the repository owner to create a tag"
            return -1
            
        version = tags[-1]
        
    url = 'https://nodeload.github.com/OpenMDAO-Plugins/%s/tarball/%s' % (name, version)
    print url
    build_docs_and_install(name, version, findLinks)

        
def update_libpath(options=None):
    """Find all of the shared libraries in the current virtual environment and
    modify the activate script to put their directories in LD_LIBRARY_PATH
    (or its equivalent).
    """
    ldict = {
        'linux2': 'LD_LIBRARY_PATH',
        'linux': 'LD_LIBRARY_PATH',
        'darwin': 'DYLD_LIBRARY_PATH',
        }
    libpathvname = ldict[sys.platform]
    
    if options is None:
        parser = ArgumentParser(description="adds any shared library paths"
                                " found in the current python environment to"
                                " %s" % libpathvname)
        parser.usage = "update_libpath [options]"
        options = parser.parse_args()
    
    if libpathvname:
        topdir = os.path.dirname(os.path.dirname(sys.executable))
        bindir = os.path.join(topdir, 'bin')
        pkgdir = os.path.join(topdir, 'lib',
                              'python%s.%s' % sys.version_info[:2], 
                              'site-packages')
        sofiles = [os.path.abspath(x) for x in find_files(pkgdir, '*.so')]
                      
        final = set()
        for fname in sofiles:
            pyf = os.path.splitext(fname)[0]+'.py'
            if not os.path.exists(pyf):
                final.add(os.path.dirname(fname))
                
        subdict = { 'libpath': libpathvname,
                    'add_on': os.pathsep.join(final)
                    }
                    
        if len(final) > 0:
            activate_lines = [
            '# BEGIN MODIFICATION\n',
            'if [ -z "$%(libpath)s" ] ; then\n',
            '   %(libpath)s=""\n',
            'fi\n',
            '\n',
            '%(libpath)s=$%(libpath)s:%(add_on)s\n',
            'export %(libpath)s\n',
            '# END MODIFICATION\n',
            '\n',
            ]
            absbin = os.path.abspath(bindir)
            activate_fname = os.path.join(absbin, 'activate')
            with open(activate_fname, 'r') as inp:
                lines = inp.readlines()
                try:
                    idx = lines.index(activate_lines[0])
                    del lines[idx:idx+len(activate_lines)]
                except ValueError:
                    pass
                
                idx = lines.index('export PATH\n')
                lines[idx+2:idx+2] = activate_lines
                
            content = ''.join(lines)
            
            with open(activate_fname, 'w') as out:
                out.write(content % subdict)

            print "\nThe 'activate' file has been updated with new values" \
                  " added to %s" % libpathvname
            print "You must deactivate and reactivate your virtual environment"
            print "for thechanges to take effect\n"

    
# This requires Internet connectivity to github.
def build_docs_and_install(name, version, findlinks):  # pragma no cover
    tdir = tempfile.mkdtemp()
    startdir = os.getcwd()
    os.chdir(tdir)
    try:
        tarpath = download_github_tar('OpenMDAO-Plugins', name, version)
        
        # extract the repo tar file
        tar = tarfile.open(tarpath)
        tar.extractall()
        tar.close()
        
        files = os.listdir('.')
        files.remove(os.path.basename(tarpath))
        if len(files) != 1:
            raise RuntimeError("after untarring, found multiple directories: %s"
                               % files)
        
        # build sphinx docs
        os.chdir(files[0]) # should be in distrib directory now
        check_call(['plugin', 'build_docs', files[0]])
        
        # create an sdist so we can query metadata for distrib dependencies
        check_call([sys.executable, 'setup.py', 'sdist', '-d', '.'])
        
        if sys.platform.startswith('win'):
            tars = fnmatch.filter(os.listdir('.'), "*.zip")
        else:
            tars = fnmatch.filter(os.listdir('.'), "*.tar.gz")
        if len(tars) != 1:
            raise RuntimeError("should have found a single archive file,"
                               " but found %s instead" % tars)

        check_call(['easy_install', '-NZ', tars[0]])
        
        # now install any dependencies
        metadict = get_metadata(tars[0])
        reqs = metadict.get('requires', [])
        done = set()
        
        while reqs:
            r = reqs.pop()
            if r not in done:
                done.add(r)
                ws = WorkingSet()
                req = Requirement.parse(r)
                dist = ws.find(req)
                if dist is None:
                    check_call(['easy_install', '-NZ', '-f', findlinks, r])
                    dist = ws.find(req)
                    if dist is None:
                        raise RuntimeError("Couldn't find distribution '%s'" % r)
                    dist.activate()
                    dct = get_metadata(dist.egg_name().split('-')[0])
                    for new_r in dct.get('requires', []):
                        reqs.append(new_r)
    finally:
        os.chdir(startdir)
        shutil.rmtree(tdir, ignore_errors=True)


def _plugin_build_docs(destdir, cfg):
    """Builds the Sphinx docs for the plugin distribution, assuming it has
    a structure like the one created by plugin quickstart.
    """
    name = cfg.get('metadata', 'name')
    version = cfg.get('metadata', 'version')
    
    path_added = False
    try:
        docdir = os.path.join(destdir, 'docs')
        srcdir = os.path.join(destdir, 'src')
        
        # have to add srcdir to sys.path or autodoc won't find source code
        if srcdir not in sys.path:
            sys.path[0:0] = [srcdir]
            path_added = True
            
        sphinx.main(argv=['', '-E', '-a', '-b', 'html',
                          '-Dversion=%s' % version,
                          '-Drelease=%s' % version,
                          '-d', os.path.join(srcdir, name, 'sphinx_build', 'doctrees'), 
                          docdir, 
                          os.path.join(srcdir, name, 'sphinx_build', 'html')])
    finally:
        if path_added:
            sys.path.remove(srcdir)
    
    
def plugin_build_docs(parser, options, args=None):
    """A command line script (plugin build_docs) points to this.  It builds the
    Sphinx documentation for the specified distribution directory.  
    If no directory is specified, the current directory is assumed.
    
    usage: plugin build_docs [dist_dir_path]
    
    """
    if args is not None and len(args) > 1:
        print_sub_help(parser, 'build_docs')
        return -1

    if args:
        dist_dir = args[0]
    else:
        dist_dir = '.'
    dist_dir = os.path.abspath(os.path.expandvars(os.path.expanduser(dist_dir)))
    _verify_dist_dir(dist_dir)

    cfgfile = os.path.join(dist_dir, 'setup.cfg')
    cfg = SafeConfigParser(dict_type=OrderedDict)
    cfg.readfp(open(cfgfile, 'r'), cfgfile)
    
    cfg.set('metadata', 'entry_points', 
            _get_entry_points(os.path.join(dist_dir, 'src')))
    
    templates, class_templates, test_template = _load_templates()
    template_options = _get_template_options(dist_dir, cfg)

    dirstruct = {
        'docs': {
            'conf.py': templates['conf.py'] % template_options,
            'pkgdocs.rst': _get_pkgdocs(cfg),
            'srcdocs.rst': _get_srcdocs(dist_dir, template_options['name']),
            },
        }
    
    build_directory(dirstruct, force=True, topdir=dist_dir)
    _plugin_build_docs(dist_dir, cfg)
    return 0

    
def plugin_list(parser, options, args=None):
    """ List github/external/built-in plugins. """
    if args:
        print_sub_help(parser, 'list')
        return -1
    
    # Requires Internet to access github.
    if options.github:  # pragma no cover
        _list_github_plugins()
        return 0
    
    groups = []
    for group in options.groups:
        if not group.startswith('openmdao.'):
            group = 'openmdao.'+group
        groups.append(group)
        
    show_all = (options.external == options.builtin)
    if show_all:
        title_type = ''
    elif options.external:
        title_type = 'external'
    else:
        title_type = 'built-in'
        
    title_groups = ','.join([g.split('.')[1] for g in groups])
    parts = title_groups.rsplit(',', 1)
    if len(parts) > 1:
        title_groups = ' and '.join(parts)
    
    if not groups:
        groups = None
    all_types = get_available_types(groups)

    plugins = set()
    for type in all_types:
        if show_all:
            plugins.add((type[0], type[1]))
        else:
            name = type[0].split('.')[0]
            if name == 'openmdao':
                if options.builtin:
                    plugins.add((type[0], type[1]))
            else:
                if options.external:
                    plugins.add((type[0], type[1]))
            
    title = "Installed %s %s plugins" % (title_type, title_groups)
    title = title.replace('  ', ' ')
    under = '-'*len(title)
    print ""
    print title
    print under
    print ""
    for plugin in sorted(plugins):
        print plugin[0], plugin[1]
        
    print "\n"

    return 0


def print_sub_help(parser, subname):
    """Prints a usage message for the given subparser name."""
    for obj in parser._subparsers._actions:
        if obj.dest != 'help':
            obj.choices[subname].print_help()
            return
    raise NameError("unknown subparser name '%s'" % subname)


# Requires Internet to access github.
def _list_github_plugins():  # pragma no cover
    url = 'https://api.github.com/orgs/OpenMDAO-Plugins/repos?type=public'
    
    print "\nAvailable plugin distributions"
    print "==============================\n"
    
    resp = urllib2.urlopen(url)
    for line in resp.fp:
        text = json.loads(line)
        for item in sorted(text):
            print '%20s -- %s' % (item['name'], item['description'])
        print '\n'
        

def _get_plugin_parser():
    """Sets up the plugin arg parser and all of its subcommand parsers."""
    
    top_parser = ArgumentParser()
    subparsers = top_parser.add_subparsers(title='commands')
    
    parser = subparsers.add_parser('list', help = "List installed plugins")
    parser.usage = "plugin list [options]"
    parser.add_argument("--github", 
                        help='List plugins in the official Openmdao-Plugins'
                             ' repository on github', 
                        action='store_true')
    parser.add_argument("-b", "--builtin", 
                        help='List all installed plugins that are part of the'
                             ' OpenMDAO distribution', 
                        action='store_true')
    parser.add_argument("-e", "--external", 
                        help='List all installed plugins that are not part of'
                             ' the OpenMDAO distribution', 
                        action='store_true')
    parser.add_argument("-g", "--group", action="append", type=str,
                        dest='groups', default=[], 
                        choices=[p.split('.',1)[1] for p in plugin_groups.keys()],
                        help="specify plugin group")
    parser.set_defaults(func=plugin_list)
    
    
    parser = subparsers.add_parser('install', 
                                   help="install an OpenMDAO plugin into the"
                                        " current environment")
    parser.usage = "plugin install [plugin_distribution] [options]"
    parser.add_argument('dist_name',
                        help='name of plugin distribution'
                             ' (defaults to distrib found in current dir)', 
                        nargs='?')
    parser.add_argument("--github", 
                        help='Find plugin in the official OpenMDAO-Plugins'
                             ' repository on github', 
                        action='store_true')
    parser.add_argument("-f", "--find-links", action="store", type=str, 
                        dest='findlinks', default='http://openmdao.org/dists',
                        help="URL of find-links server")
    parser.add_argument("--all", help='Install all plugins in the official OpenMDAO-Plugins'
                        ' repository on github', action='store_true')
    parser.set_defaults(func=plugin_install)
    
    
    parser = subparsers.add_parser('build_docs', 
                                   help="build sphinx doc files for a plugin")
    parser.usage = "plugin build_docs <dist_dir_path>"
    parser.add_argument('dist_dir_path',
                        help='path to distribution source directory')
    parser.set_defaults(func=plugin_build_docs)

    
    parser = subparsers.add_parser('docs', 
                                   help="display docs for a plugin")
    parser.usage = "plugin docs <plugin_dist_name>"
    parser.add_argument('plugin_dist_name', help='name of plugin distribution')
    parser.add_argument("-b", "--browser", action="store", type=str, 
                        dest='browser', choices=webbrowser._browsers.keys(),
                        help="browser name")
    parser.set_defaults(func=plugin_docs)
    
    
    parser = subparsers.add_parser('quickstart',
                                   help="generate some skeleton files for a plugin")
    parser.usage = "plugin quickstart <dist_name> [options]"
    parser.add_argument('dist_name', help='name of distribution')
    parser.add_argument("-v", "--version", action="store", type=str,
                        dest='version', default='0.1',
                        help="version id of the plugin (defaults to 0.1)")
    parser.add_argument("-c", "--class", action="store", type=str,
                        dest='classname', help="plugin class name")
    parser.add_argument("-d", "--dest", action="store", type=str, dest='dest', 
                        default='.',
                        help="directory where new plugin directory will be"
                             " created (defaults to current dir)")
    parser.add_argument("-g", "--group", action="store", type=str, dest='group',
                        default = 'openmdao.component',
                        help="specify plugin group %s (defaults to"
                             " 'openmdao.component')" % plugin_groups.keys())
    parser.set_defaults(func=plugin_quickstart)
    
    
    parser = subparsers.add_parser('makedist',
                                   help="create a source distribution for a plugin")
    parser.usage = "plugin makedist [dist_dir_path]"
    parser.add_argument('dist_dir_path', nargs='?',
                        default='.',
                        help='directory where plugin distribution is found'
                             ' (defaults to current dir')
    parser.set_defaults(func=plugin_makedist)
    
    return top_parser


# Calls sys.exit().
def plugin():  # pragma no cover
    parser = _get_plugin_parser()
    options, args = parser.parse_known_args()
    sys.exit(options.func(parser, options, args))

