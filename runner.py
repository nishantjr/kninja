import argparse
import functools
import os
import sys
from collections import OrderedDict

class KProject():
    ''' A KProject defines the directory structure of a project '''

    def __init__(self, extdir = 'ext'):
        self._extdir = extdir
        self._k_definitions = OrderedDict()

    def extdir(self, *paths):
        ''' Directory for storing submodules used by KNinja '''
        return os.path.join(self._extdir, *paths)

    def krepodir(self, *paths):
        ''' Path to the K Framework '''
        return self.extdir('k', *paths)

    def pandoc_tangle_repository(self, *paths):
        ''' pandoc-tangle repository '''
        return self.extdir('pandoc-tangle', *paths)

    def kbindir(self, *paths):
        ''' Directory where K binaries are stored '''
        return self.krepodir("k-distribution/target/release/k/bin", *paths)

    def kninjadir(self, *paths):
        ''' Path to the KNinja project '''
        return os.path.join(os.path.dirname(__file__), *paths)

    def builddir(self, *paths):
        ''' The project's main build directory '''
        return os.path.join('.build', *paths)

class KDefinition():
    def __init__( self
                , proj
                , alias
                , backend
                , directory = None
                , krun_flags = ''
                , krun_env = ''
                , kprove_flags = ''
                , kprove_env = ''
                ):
        self._proj = proj
        self._alias = alias
        self._backend = backend
        self._directory = directory
        self._krun_env = krun_env
        self._krun_flags = krun_flags
        self._kprove_env = kprove_env
        self._kprove_flags = kprove_flags

        self.proj._k_definitions[alias] = self
        if self._directory == None:
            self._directory = proj.builddir('defn', alias)

    @property
    def proj(self):    return self._proj
    @property
    def alias(self):   return self._alias
    @property
    def backend(self): return self._backend
    def directory(self, *path):
        return os.path.join(self._directory, *path)

class KRunner():
    def __init__(self, proj, default_definition = None):
        self.parser = argparse.ArgumentParser()
        self.proj = proj
        parser = self.parser
        self.default_definition = default_definition

        subparsers = parser.add_subparsers()

        kast_parser = subparsers.add_parser('kast', help = 'Run a program against a definition')
        self.add_definition_argument(kast_parser)
        kast_parser.add_argument('program', help = 'Path to program')
        kast_parser.add_argument('args', nargs = argparse.REMAINDER, help = 'Arguments to pass to K')
        kast_parser.set_defaults(func = functools.partial(self.execute_kast, self))

        run_parser = subparsers.add_parser('run', help = 'Run a program against a definition')
        self.add_definition_argument(run_parser)
        run_parser.add_argument('program', help = 'Path to program')
        run_parser.add_argument('args', nargs = argparse.REMAINDER, help = 'Arguments to pass to K')
        run_parser.set_defaults(func = functools.partial(self.execute_krun, self))

        prove_parser = subparsers.add_parser('prove', help = 'Use KProve to check a specification')
        self.add_definition_argument(prove_parser)
        prove_parser.add_argument('specification', help = 'Path to spec')
        prove_parser.add_argument('args', nargs = argparse.REMAINDER, help = 'Arguments to pass to K')
        prove_parser.set_defaults(func = functools.partial(self.execute_kprove, self))

    def add_definition_argument(self, subparser):
        defs = self.proj._k_definitions
        subparser.add_argument( '--definition'
                              , choices = list(defs) # Keys in the OrderedDict
                              , default = list(defs)[0]
                              , help = 'Alias of definition'
                              )

    def main(self, argv = sys.argv[1:]):
        namespace = self.parser.parse_args(argv)
        namespace.func.func(namespace)

    def execute_kast(self, args):
        os.execlp( self.proj.kbindir('kast')
                 , self.proj.kbindir('kast')
                 , '--directory', self.proj._k_definitions[args.definition].directory()
                 , args.program
                 , *args.args
                 )
    def execute_krun(self, args):
        definition = self.proj._k_definitions[args.definition]
        binary = self.proj.kbindir('krun')
        os.execlp( binary
                 , self.proj.kbindir('krun')
                 , '--directory', definition.directory()
                 , args.program
                 , *self.proj._k_definitions[args.definition]._krun_flags.split()
                 , *args.args
                 )
    def execute_kprove(self, args):
        os.execlp( self.proj.kbindir('kprove')
                 , self.proj.kbindir('kprove')
                 , '--directory', self.proj._k_definitions[args.definition].directory()
                 , args.specification
                 , *self.proj._k_definitions[args.definition]._kprove_flags.split()
                 , *args.args
                 )
