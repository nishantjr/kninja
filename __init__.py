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
import argparse

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
def append_extension(path, extension):
    return path + '.' + extension

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

class KDefinition():
    def __init__( self
                , proj
                , alias
                , directory
                , kompiled_dirname
                , target
                , backend
                , runner_script
                , krun_flags = ''
                , krun_extension = 'krun'
                , krun_env = ''
                , kprove_extension = 'kprove'
                ):
        self._alias = alias
        self._backend = backend
        self._directory = directory
        self._kprove_extension = kprove_extension
        self._krun_env = krun_env
        self._krun_extension = krun_extension
        self._krun_flags = krun_flags
        self._proj = proj
        self._runner_script = runner_script
        self._target = target

    @property
    def proj(self):
        return self._proj

    @property
    def target(self):
        return self._target

    """ High Level Interface """

    def directory(self, *path):
        return os.path.join(self._directory, *path)

    def tests(self, expected = None, glob = None, alias = None, default = True, flags = []):
        inputs = []
        if glob is not None:
            inputs += glob_module.glob(glob)
        ret = []
        for input in inputs:
            e = expected
            if e is None:
                e = append_extension(input, 'expected')
            test = self.proj.source(input) \
                            .then(self.runner_script(mode = 'run', flags = flags)) \
                            .then(self.proj.check(expected = e))
            if default: test.default()
            ret += [test]
        if alias is not None:
            ret = self.proj.alias(alias, ret)
        return ret

    def proofs(self, glob = None, alias = None, default = True, expected = None, flags = []):
        inputs = []
        if expected is None:
           expected = self.proj.kninjadir('kprove.expected')
        if glob is not None:
            inputs += glob_module.glob(glob)
        ret = []
        for input in inputs:
            test = self.proj.source(input) \
                            .then(self.runner_script(mode = 'prove', flags = flags)) \
                            .then(self.proj.check(expected))
            if default: test.default()
            ret += [test]
        if alias is not None:
            ret = self.proj.alias(alias, ret)
        return ret

    """ Low Level Interface """

    # mode: run|prove
    def runner_script(self, mode, flags = []):
        # TODO: We use a different rule for each kompiled definition, since
        # the `ext` flag is tied to the rule instead of the build edge
        return self.proj.rule( 'runner-script-' + self._alias + '-' + mode
                             , description = mode + ': ' + self._alias + ' $in'
                             , command = self._runner_script + ' ' + mode + ' --definition "$definition" "$in" ' + " ".join(flags) + ' > "$out"'
                             , ext = self._alias + '-' + mode
                             ) \
                             .variable('definition', self._alias) \
                             .implicit([self.target])

    def krun(self, krun_flags = '', extension = None, runner = None):
        return self.proj.rule( 'krun'
                             , description = 'krun: $in ($directory)'
                             , command = '$env "$k_bindir/krun" $flags --directory $directory $in > $out'
                             , ext = self._krun_extension
                             ) \
                             .variable('directory', self.directory()) \
                             .variable('flags', self._krun_flags + ' ' + krun_flags) \
                             .variable('env', self._krun_env) \
                             .implicit([self.target])

    def kast(self):
        return self.proj.rule( 'kast'
                             , description = 'kast: $in ($directory)'
                             , command     = '$env "$k_bindir/kast" $flags --directory "$directory" "$in" > "$out"'
                             , ext = 'kast'
                             ) \
                             .variables(directory = self.directory()) \
                             .implicit([self.target])

    def kprove(self):
        # kprove prints errors to stdout, instead of stderror
        # The kprove rule `cat`s its output after failing for convenience.
        # I'm not sure if there is a better way.
        return self.proj.rule( 'kprove'
                             , description = 'kprove: $in ($directory)'
                             , command     = '$env "$k_bindir/kprove" $flags --directory "$directory" "$in" > "$out" || (cat "$out"; false)'
                             , ext = self._kprove_extension
                             ) \
                             .variables(directory = self.directory()) \
                             .implicit([self.target])

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

# KProject
# ========
#
# A KProject manages a single `ninja` build file.

class KProject(ninja.ninja_syntax.Writer):
    def __init__(self, extdir = 'ext'):
        self.written_rules = {}
        self._backend_targets =  dict(java=None, ocaml=None, haskell=None, llvm=None)
        self._target_configure_opam = None
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
        parser = argparse.ArgumentParser()
        parser.add_argument('--opamswitch', default = '4.06.1+k')
        namespace, remaining = parser.parse_known_args(argv)
        os.environ["OPAMSWITCH"] = namespace.opamswitch
        os.execlp('ninja', 'ninja', '-f', self.builddir('generated.ninja'), *remaining)

    def tangle(self, input, output = None, selector = '.k'):
        input_target = self.source(input)
        if (output is None):
            output = self.place_in_output_dir(replace_extension(input, 'k'))
        return input_target.then(self.rule_tangle().output(output).variable('tangle_selector', selector))

    def definition( self
                  , alias
                  , backend
                  , main
                  , runner_script
                  , other = []
                  , directory = None
                  , tangle_selector = '.k'
                  , flags = ''
                  ):
        if directory is None:
            directory = self.builddir('defn', alias)

        # If a source file has extension '.md', tangle it:
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

        kompiled_dir =  os.path.join(directory, basename_no_ext(main.path) + '-kompiled')
        output = None
        env = ''
        implicit_inputs = [self.build_k(backend)]
        if backend == 'ocaml':
            output = os.path.join(kompiled_dir, 'interpreter')
            implicit_inputs += [self.configure_opam()]
            env = 'opam config exec --'
        elif backend == 'llvm':
            output = os.path.join(kompiled_dir, 'interpreter')
        elif backend == 'java':
            output = os.path.join(kompiled_dir, 'timestamp')
        elif backend == 'haskell':
            output = os.path.join(kompiled_dir, 'kore.txt')
        else:
            assert false, 'Unknown backend "' + backend + "'"

        target = main.then(self.rule_kompile()                    \
                               .output(output)                    \
                               .implicit(other)                   \
                               .implicit(implicit_inputs) \
                               .variable('backend', backend)      \
                               .variable('directory', directory)  \
                               .variable('env', env)              \
                               .variable('flags', '-I ' + directory + ' ' + flags)  \
                          ).alias(alias)
        return KDefinition( self, alias, directory, kompiled_dir, target
                          , runner_script = runner_script
                          , krun_extension = alias + '-krun', krun_env = env
                          , kprove_extension = alias + '-kprove'
                          , backend = backend
                          )

    def alias(self, name, targets):
        self.build(name, 'phony', Target.to_paths(targets))
        return Target(self, name)

    def default(self, targets):
        super().default(Target.to_paths(targets))

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

# If a (relative) output path is not in the buiddir, place it there. Otherwise
# return the same path unchanged.
    def place_in_output_dir(self, path):
        return place_in_dir(path, self.builddir(''))

# Generating the Ninja build script
# =================================

    def generate_ninja(self):
        self.comment('This is a generated file')
        self.newline()
        self.variable('ninja_required_version', '1.7')
        self.variable('builddir', self.builddir())
        # TODO: Remove underscores for consistancy
        self.variable('k_repository', self.krepodir())
        self.variable('k_bindir', self.kbindir())
        self.variable('tangle_repository', self.pandoc_tangle_repository())
        self.rule('clean'
                 , description = 'cleaning'
                 , command = 'ninja -t clean ; rm -rf "$builddir" ; git submodule update --init --recursive'
                 )
        self.build('clean', 'clean')

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
                          description = None,
                          command     = 'git submodule update $flags --init "$path" && touch "$out"'
                        ) \
                   .output(timestamp_file) \
                   .variable('path', path)

    def init_tangle_submodule(self):
        if self._tangle_repo_init is None:
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
        if self._k_repo_init is None:
            self._k_repo_init = self.dotTarget().then(
                    self.rule_git_submodule_init( path = self.extdir('k')
                                                , timestamp_file = self.builddir('k.init')
                                                ).variable('flags', '--recursive'))
        return self._k_repo_init

    def rule_configure_opam(self):
        return self.rule( 'k-configure-opam-dev'
                        , description = '$command'
                        , command = "opam init --no-setup && $k_bindir/k-configure-opam-dev </dev/null && touch $out"
                        ) \
                   .variable('pool', 'console') \
                   .output(self.builddir('k-configure-opam.timestamp'))

    def configure_opam(self):
       if not(self._target_configure_opam):
           self._target_configure_opam = \
                self.dotTarget().then(self.rule_configure_opam()
                                          .implicit([self.build_k(backend = 'ocaml')]))
       return self._target_configure_opam

    def rule_build_k(self, backend):
        flags = ''
        implicit = [self.init_k_submodule()]
        if backend == 'ocaml':
            flags = '-Dllvm.backend.skip -Dhaskell.backend.skip'
        if backend == 'java':
            flags = '-Dllvm.backend.skip -Dhaskell.backend.skip'
        if backend == 'haskell':
            flags = '-Dllvm.backend.skip'
        if backend == 'llvm':
            flags = '-Dhaskell.backend.skip -Dproject.build.type=Debug'
        return self.rule( 'build-k'
                        , description = 'build K: $backend'
                        , command =    '(  cd $k_repository ' +
                                       '&& mvn package -DskipTests $flags' +
                                       ')' +
                                    '&& touch $out'
                        ) \
                   .output('$builddir/kbackend-' + backend) \
                   .pool('console') \
                   .implicit(implicit) \
                   .variable('flags', flags) \
                   .variable('backend', backend)

    def build_k(self, backend):
        if not(self._backend_targets[backend]):
            self._backend_targets[backend] = self.dotTarget().then(self.rule_build_k(backend))
        return self._backend_targets[backend]

    def rule_kompile(self):
        return  self.rule( 'kompile'
                         , description = 'kompile: $in ($backend)'
                         , command     = '$env "$k_bindir/kompile" --backend "$backend" $flags '
                                       + '--directory "$directory" $in'
                         )

    def ocamlfind(self):
        return self.rule( 'ocamlfind'
                        , description = 'ocamlfind: $out'
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
        assert false, "Unsupported"

    def check(self, expected):
        return self.rule( 'check-test-result'
                        , description = 'diff: $in'
                        , command = 'git diff --color=always --no-index $flags "$expected" "$in"'
                        , ext = 'test') \
                   .variable('expected', expected) \
                   .implicit([expected])
