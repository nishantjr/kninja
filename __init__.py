"""

KNinja (and Ninja's) build definitions form a labelled multigraph where:

-   The nodes are targets: generally files, but can also be phoney targets
-   The labels are rules: A command to run, parameterised over a set of
    variables.
-   The edges (called build edges): specify how to build one or more targets
    from zero or more inputs. Edges allow setting values for
    variables used in their label.

"""

import kninja.ninja.ninja_syntax
import copy
import glob as glob_module
import os
import sys

def basename_no_ext(path):
    return os.path.splitext(os.path.basename(path))[0]
def get_extension(path):
    return os.path.splitext(path)[1][1:]
def is_subpath(path, parent):
    return os.path.abspath(path).startswith(os.path.abspath(parent) + os.sep)
def place_in_dir(path, dir):
    # TODO: This is very simplistic, assumes that all paths are relative to topdir,
    # or are prefixed with builddir
    assert path[0] != '/', 'place_in_dir only supports relative paths'
    if not(is_subpath(path, dir)):
        path = os.path.join(dir, path)
    return path
def replace_extension(path, new_extension):
    return os.path.splitext(path)[0] + '.' + new_extension

class Target():
    def __init__(self, proj, path):
        self.proj = proj
        self.path = path
        self._alias = None

    def __str__(self):
        return self.path

    def then(self, rule):
        target = rule.get_build_edge_target_path(self)
        return rule.build_edge(self.proj, self, target)

    def alias(self, alias):
        self._alias = alias
        self.proj.build(alias, 'phony', self.path)
        return self

    def default(self):
        self.proj.default(self.path)
        return self

    @staticmethod
    def to_paths(value):
        if value is None:
            return None
        if isinstance(value, list):
            return list(map(Target.to_paths, value))
        if isinstance(value, str):
            return value
        if isinstance(value, Target):
            return value.path

class KDefinition(Target):
    def __init__(self, proj, kompiled_dirname, target, krun_flags = ''):
        self._directory = os.path.dirname(kompiled_dirname)
        self._krun_flags = krun_flags
        assert os.path.dirname(target) == kompiled_dirname \
             , "target must be a file in the kompiled dir\n\n\ttarget = %s\n\tkompiled_dirname = %s" \
               % (target, kompiled_dirname)
        super().__init__(proj, target)

    """ High Level Interface """

    def tests(self, expected, inputs = [], glob = None, alias = None):
        if glob != None:
            inputs += glob_module.glob(glob)
        ret = []
        for input in inputs:
            test = self.proj.source(input) \
                            .then(self.krun()) \
                            .then(self.proj.check(expected = expected)) \
                            .default()
            ret += [test]
        if alias != None:
            ret = self.proj.alias(alias, ret)
        return ret

    def proofs(self, inputs = [], glob = None, alias = None):
        if glob != None:
            inputs += glob_module.glob(glob)
        ret = []
        for input in inputs:
            test = self.proj.source(input) \
                            .then(self.kprove()) \
                            .default()
            ret += [test]
        if alias != None:
            ret = self.proj.alias(alias, ret)
        return ret

    """ Low Level Interface """

    def directory(self, *path):
        return os.path.join(self._directory, *path)

    def krun(self, krun_flags = '', extension = None):
        if not(extension):
            if self._alias: extension = self._alias
            else:           extension = 'krun'
        return self.proj.rule( 'krun'
                             , description = 'krun: $in ($directory)'
                             , command = '$k_bindir/krun $flags --debug --directory $directory $in > $out'
                             , ext = extension
                             ) \
                             .variables( directory = self.directory()
                                       , flags = self._krun_flags + ' ' + krun_flags
                                       ) \
                             .implicit([self.path])

    def kast(self):
        return self.proj.rule( 'kast'
                             , description = 'kast: $in ($directory)'
                             , command     = '"$k_bindir/kast" $flags --debug --directory "$directory" "$in" > "$out"'
                             , ext = 'kast'
                             ) \
                             .variables(directory = self.directory()) \
                             .implicit([self.path])

    def kprove(self):
        # The kprove command `cat`s its output after failing for convenience.
        # I'm not sure if there is a better way.
        return self.proj.rule( 'kast'
                             , description = 'kprove: $in ($directory)'
                             , command     = '"$k_bindir/kprove" $flags --directory "$directory" "$in" > "$out" || (cat "$out"; false)'
                             , ext = 'kprove'
                             ) \
                             .variables(directory = self.directory()) \
                             .implicit([self.path])

class Rule():
    def __init__(self, name, description, command, ext = None):
        self.name = name
        self.description = description
        self.command = command
        self._ext = ext
        self._output           = None
        self._implicit         = []
        self._implicit_outputs = []
        self._pool             = None
        self._variables        = {}

    def ext(self, ext)                          : r = copy.copy(self); r._ext               = ext              ; return r
    def output(self, output)                    : r = copy.copy(self); r._output            = output           ; return r
    def implicit(self, implicit)                : r = copy.copy(self); r._implicit         += implicit         ; return r
    def implicit_outputs(self, implicit_outputs): r = copy.copy(self); r._implicit_outputs += implicit_outputs ; return r
    def pool(self, pool)                        : r = copy.copy(self); r._pool              = pool             ; return r
    def variables(self, **variables):
        r = copy.copy(self)
        # Merge the two dictionaries
        r._variables = { **self._variables, **variables }
        return r
    def variable(self, name, value):
        r = copy.copy(self)
        r._variables[name] = value
        return r

    def get_build_edge_target_path(self, source):
        if self._output: return self._output
        if self._ext:
            path = source.proj.place_in_output_dir(source.path + '.' + self._ext)
            return path
        raise ValueError("Dont know how to generate target path for rule '%s'" % (self.name))

    def build_edge(self, proj, source, target):
        proj.build( rule = self.name
                  , inputs = source.path, outputs = target, implicit = Target.to_paths(self._implicit)
                  , implicit_outputs = self._implicit_outputs, pool = self._pool, variables = self._variables
                  )
        return Target(proj, target)

class KompileRule(Rule):
    def __init__(self):
        super().__init__('kompile', 'foo', 'bar')

    def kompiled_dirname(self, source):
        return self._variables.get('directory') + '/' + basename_no_ext(source.path) + '-kompiled'

    def get_build_edge_target_path(self, source):
        if self._output: return self._output
        return  self.kompiled_dirname(source) + '/timestamp'

    def build_edge(self, proj, source, target):
        super().build_edge(proj, source, target)
        return KDefinition(proj, self.kompiled_dirname(source), target)

# KProject
# ========
#
# A KProject manages a single `ninja` build file.

class KProject(ninja.ninja_syntax.Writer):
    def __init__(self, extdir = 'ext'):
        self.written_rules = {}
        self._backend_targets =  dict(java=None, ocaml=None, haskell=None, llvm=None)
        self._tangle_repo_init = None
        self._k_repo_init = None
        self._extdir = extdir

        if not os.path.exists(self.builddir()):
            os.mkdir(self.builddir())
        super().__init__(open(self.builddir('generated.ninja'), 'w'))
        self.generate_ninja()

    """ High level interface """

    def main(self, argv = sys.argv[1:]):
        self.close()
        os.execlp('ninja', 'ninja', '-f', self.builddir('generated.ninja'), *argv)

    def tangle(self, input, output = None, selector = '.k'):
        input_target = self.source(input)
        if (output == None):
            output = self.place_in_output_dir(replace_extension(input, 'k'))
        return input_target.then(self.rule_tangle().output(output).variable('tangle_selector', selector))

    def definition( self
                  , alias
                  , backend
                  , main
                  , directory
                  , tangle_selector = '.k'
                  , flags = ''
                  , other = []
                  ):
        def target_from_source(source):
            if get_extension(source) == 'md':
                return self.tangle( source
                                  , selector = tangle_selector
                                  , output = place_in_dir( replace_extension(source, 'k')
                                                         , directory
                                                         )
                                  )
            return self.source(source)
        main = target_from_source(main)
        other = map(target_from_source, other)
        return main.then(self.kompile(backend = backend)       \
                             .implicit(other)                  \
                             .variable('directory', directory) \
                             .variable('flags', flags)         \
                        ).alias(alias)

    def alias(self, alias, targets):
        self.build(alias, 'phony', Target.to_paths(targets))
        return Target(self, alias)

# Directory Layout
# ================
#
# Users may subclass KProjects, and override these methods for alternate project
# layouts.

# Dependency Paths
# ----------------

# Directory for storing submodules used by KNinja
    def extdir(self, *paths):
        return os.path.join(self._extdir, *paths)

# Path to the K Framework
    def krepodir(self, *paths):
        return self.extdir('k', *paths)

# pandoc-tangle repository
    def pandoc_tangle_repository(self, *paths):
        return self.extdir('pandoc-tangle', *paths)

# Directory where K binaries are stored
    def kbindir(self, *paths):
        return self.krepodir("k-distribution/target/release/k/bin", *paths)

# Path to the KNinja project
    def kninjadir(self, *paths):
        return os.path.join(os.path.dirname(__file__), *paths)

# Build Paths
# -----------

# The project's main build directory
    def builddir(self, *paths):
        return os.path.join('.build', *paths)

# Directory to output tangled files in
    def tangleddir(self, *paths):
        return self.builddir('tangled', *paths)

# Directory to build OPAM in. We use this instead of `~/.opam` so that we don't
# intefere with system functionality.
    def opamroot(self, *paths):
        return self.builddir('opam', *paths)

# If a (relative) output path is not in the buiddir, place it there. Otherwise
# return the same path unchanged.
    def place_in_output_dir(self, path):
        return place_in_dir(path, self.builddir(''))

# Generating the Ninja build script
# =================================

    def generate_ninja(self):
        self.comment('This is a generated file')
        self.newline()
        self.variable('builddir', self.builddir())
        # TODO: Remove underscores for consistancy
        self.variable('opam_root', self.opamroot())
        self.variable('k_repository', self.krepodir())
        self.variable('k_bindir', self.kbindir())
        self.variable('tangle_repository', self.pandoc_tangle_repository())

        self.include(self.kninjadir("prelude.ninja"))
        self.include(self.kninjadir('build-ocaml.ninja'))

    def rule(self, name, description, command, ext = None):
        rule = Rule(name, description, command, ext)
        if not(name in self.written_rules):
            super().rule(name, description = description, command = command)
            self.written_rules[name] = rule
        return rule

    def source(self, path):
        return Target(self, path)

    # fake target, for when a build-edge has no inputs
    # TODO: This is a hack. `then` should be moved to KProject, and take
    # a list of targets (so that a build edge can have zero, one or many outputs)
    # and a rule.
    def dotTarget(self):
        return Target(self, '')

    def rule_git_submodule_init(self, path, timestamp_file):
        return self.rule( 'git-submodule-init',
                          description = 'git submodule init $path',
                          command     = 'git submodule update $flags --init "$path" && touch "$out"'
                        ) \
                   .output(timestamp_file) \
                   .variable('path', path)

    def init_tangle_submodule(self):
        if self._tangle_repo_init == None:
            self._tangle_repo_init = self.dotTarget().then(
                    self.rule_git_submodule_init( path = self.pandoc_tangle_repository()
                                                , timestamp_file = self.pandoc_tangle_repository('tangle.lua')
                                                ))
        return self._tangle_repo_init

    def rule_tangle(self, tangle_selector = '.k', ext = 'k'):
        return self.rule( 'tangle',
                          description = 'tangle: $in',
                          command     = 'LUA_PATH=$tangle_repository/?.lua '
                                      + 'pandoc $in -o $out --metadata=code:$tangle_selector --to "$tangle_repository/tangle.lua"'
                        ) \
                   .ext('k') \
                   .implicit([self.init_tangle_submodule()]) \
                   .variables(tangle_selector = tangle_selector)

    def init_k_submodule(self):
        if self._k_repo_init == None:
            self._k_repo_init = self.dotTarget().then(
                    self.rule_git_submodule_init( path = self.extdir('k')
                                                , timestamp_file = self.builddir('k.init')
                                                ).variable('flags', '--recursive'))
        return self._k_repo_init

    def rule_build_k(self, backend):
        flags = ''
        implicit = [self.init_k_submodule()]
        if backend == 'ocaml':
            implicit += ['ocaml-deps']
            flags = '-Dllvm.backend.skip -Dhaskell.backend.skip'
        if backend == 'java':
            flags = '-Dllvm.backend.skip -Dhaskell.backend.skip'
        if backend == 'haskell':
            flags = '-Dllvm.backend.skip'
        if backend == 'llvm':
            flags = '-Dhaskell.backend.skip'
        return self.rule( 'build-k'
                        , description = 'Building K ($backend)'
                        , command =    '(  cd $k_repository ' +
                                       '&& mvn package -q -DskipTests $flags' +
                                       ')' +
                                    '&& touch $out'
                        ) \
                   .output('$builddir/kbackend-' + backend) \
                   .implicit(implicit) \
                   .variable('flags', flags) \
                   .variable('backend', backend)

    def build_k(self, backend):
        if not(self._backend_targets[backend]):
            self._backend_targets[backend] = self.dotTarget().then(self.rule_build_k(backend))
        return self._backend_targets[backend]

    def rule_kompile(self):
        self.rule( 'kompile'
                 , description = 'kompile: $in ($backend)'
                 , command     = '$k_bindir/kompile --backend "$backend" --debug $flags '
                               + '--directory "$directory" $in'
                 )
        return KompileRule()

    def kompile(self, backend):
        ret = self.rule_kompile().variables(backend = backend).implicit([self.build_k(backend)])
        return ret

    def ocamlfind(self):
        return self.rule( 'ocamlfind'
                        , description = 'ocamlfind $out'
                        , command = 'ocamlfind opt -o $out $flags $in'
                        )

    # TODO: To have the same interface as kompile, `.then()` needs to allow
    # taking a list of rules rather than a single one.
    def kompile_interpreter( self, main_file, directory
                           , additional_ml_sources = []
                           , kompile_flags = ""
                           , ocamlfind_flags = ""
                           , packages = []
                           ):
        kompile_flags += " --gen-ml-only"
        kompiledir_ml_sources_1 = [ 'constants.ml'
                                  , 'prelude.ml'
                                  , 'plugin.ml'
                                  ]
        kompiledir_ml_sources_2 = [ 'realdef.ml'
                                  , 'parser.mli'
                                  , 'parser.ml'
                                  , 'lexer.ml'
                                  , 'run.ml'
                                  ]
        kompile = self.rule_kompile().variables( flags = kompile_flags
                                               , backend = 'ocaml'
                                               , directory = directory
                                               ).implicit([self.build_k()])
        kompiled_dirname = kompile.kompiled_dirname(main_file)
        def prefix_with_kompiled_dir(f):
            return os.path.join(kompiled_dirname, f)
        ml_sources = list(map(prefix_with_kompiled_dir, kompiledir_ml_sources_1)) \
                   + additional_ml_sources \
                   + list(map(prefix_with_kompiled_dir, kompiledir_ml_sources_2))
        realdef_cmx  = os.path.join(kompiled_dirname, 'realdef.cmx')
        realdef_cmo = os.path.join(kompiled_dirname, 'realdef.cmxs')
        package_flags = map(lambda p: '-package ' + p + ' ', packages)
        interpreter = main_file.then(kompile.output(kompiled_dirname + '/interpreter.ml')) \
                     .then(self.ocamlfind().variables(flags = '-g -w -11-26 -linkpkg '
                                                            + '-I ' + kompiled_dirname + ' '
                                                            + '-I ext/blockchain-k-plugin/plugin '
                                                            + '-I ext/blockchain-k-plugin/ '
                                                            + ' '.join(package_flags)
                                                            + ' -linkpkg -linkall -thread -safe-string '
                                                            + ' '.join(Target.to_paths(ml_sources))
                                                ) \
                                     .implicit(['ocaml-deps']) \
                                     .output(os.path.join(kompiled_dirname, 'interpreter')) \
                                     .implicit_outputs([realdef_cmx])
                          )
        t = self.source(realdef_cmx) \
            .then( self.ocamlfind().variables(flags = '-shared').output(realdef_cmo) )
        return KDefinition(self, kompiled_dirname, t.path, krun_flags = '--interpret')

    def check(self, expected):
        return self.rule( 'check-test-result'
                        , description = 'Checking $in'
                        , command = 'git diff --no-index $flags $in $expected'
                        , ext = 'test') \
                   .variables(expected = expected) \
                   .implicit([expected])
