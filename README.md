KNinja is a python-based generator intended to ease the startup time for K
projects. We'd like the setup time for projects not using advanced compilation
features (such as plugins for the OCaml and LLVM backends) to be as cheap as
possible, while still simplifying common advanced usage patterns. KNinja is a
bit opinionated in the directory layout of the project (but allows for some
configuration via ninja variables).

Overview
========

`kninja` tries to expose the simplicity of Ninja in defining the build process
as a multigraph of build edges and targets while abstracting common patterns
used in K projects. Most objects exposed by the build system are either
"Targets" that represent files or phoney targets to be built, or "Rules"
used to describe how build a new target.

-   Source files are targets (constructed with `proj.source('foo.k')`)
-   Targets define a `then` function that takes a rule and returns a target.
    Thus rule applications to targets can be chained together e.g.
    `proj.source('foo.k').then(proj.tangle()...).then(proj.kompile()...)`
-   Rule applications allow a few points for customizing invocation:
    -   Many rules attempt to guess a suitable output file name to reduce
        unneccessary clutter in the definition. `rule.output(target_path)` lets
        you override this. You may also specify just the extension of to be used
        rather than the entire output path.
    -   Rules allow specifying the values to set ninja variables to (e.g.
        `rule.variables(backend = 'java')`). Typically rules wrapping command
        line commands will allow a `flags` variable for specifying additional
        parameters.
    -   Rules allow specifying additional implicit dependencies
        `rule.implicit([target1, target2])`, implicit outputs
        `rule.implicit_outputs([o1, o2])` and the ninja "pool" to use for the
        job `rule.pool('console')`.

A typical setup
===============

Here, we setup the build system for a literate K-Definition with three tests. A
more detailed example can be found here
<https://github.com/kframework/k-in-k/blob/master/lib/build.py>.

1. Add `k`, `kninja` and `pandoc-tangle` (optional) as submodules in some common directory `extdir':

   ```sh
   git submodule add https://github.com/kframework/k           $extdir/k
   git submodule add https://github.com/nishantjr/kninja       $extdir/kninja
   git submodule add https://github.com/ehildenb/pandoc-tangle $extdir/pandoc-tangle
   ```

2. Add a script `build` (we call this the "generator" script):

    ```python3
    #!/usr/bin/env python3

    import os
    import subprocess
    import sys

    # Bootstrapping
    # =============

    subprocess.check_call(['git', 'submodule', 'update', '--init', '--recursive'])
    extdir = '.build'
    sys.path.append(os.path.join(os.path.dirname(__file__), extdir))

    from kninja import *

    # Build
    # =====

    proj = KProject(extdir = extdir)
    def build_wasm(backend, flags = ''):
        return proj.definition( alias             = 'wasm-' + backend
                              , backend           = backend
                              , main              = 'test.md'
                              , other             = [ 'wasm.md', 'data.md', 'kwasm-lemmas.md' ]
                              , directory         = proj.builddir('defn', backend)
                              , runner_script     = './kwasm'
                              , flags             = '--main-module WASM-TEST --syntax-module WASM-TEST ' \
                                                  + flags
                              )
    wasm_java = build_wasm(backend = 'java')
    wasm_ocaml = build_wasm(backend = 'ocaml', flags = '-O3 --non-strict')
    wasm_haskell = build_wasm(backend = 'haskell')

    # Testing
    # =======

    concrete_backend = wasm_ocaml
    symbolic_backend = wasm_java

    def exec_tests(defn, backend):
        simple = defn.tests( glob = 'tests/simple/*.wast'
                           , alias = 'test-simple-' + backend
                           , expected = 'tests/success-' + backend + '.out'
                           , default = False
                           )
        exec = proj.alias( name = 'test-exec-' + backend
                         , targets = simple
                         )
        return exec

    def proof_tests(defn, backend):
        return defn.proofs( glob = 'tests/proofs/*-spec.k'
                          , alias = 'test-proofs-' + backend
                          , default = False
                          )

    exec_tests(wasm_java, 'java')
    exec_tests(wasm_ocaml, 'ocaml')
    proof_tests(wasm_java, 'java')
    proof_tests(wasm_haskell, 'haskell')

    proj.alias(name = 'test-exec',   targets = 'test-exec-java')
    proj.alias(name = 'test-simple', targets = 'test-simple-java')
    proj.alias(name = 'test-proofs', targets = 'test-proofs-java')
    proj.default(['test-exec', 'test-simple', 'test-proofs'])

    # Main
    # ====

    proj.main()
    ```

   Make executable: `chmod u+x build`

Things we'd like
================

-   (easy) `implicit`, `implicit_outputs` etc should allow taking strings and
    targets in addition to lists.

-   Allow composing rules in to new rule: This will remove the need to define
    auxilary functions (which tend to have a different interface from rules) for
    composing rules together.

-   The `kompile` object returns a special target: a `KDefinition`.
    `KDefinition` have most of the information needed to run a program. This
    could be used to define an easy interface for running these programs with
    invocation sepefic options (e.g.
    `./build krun-plutus t/my-program --debugger`). (Really, this could work for any rule?)

Bugs
====

*   Rules should be immutable:
    `Target.{outputs, implicit, implicit_outputs, ...}` should return an updated
    copy rather than modifying the original rule. This will prevent these
    from accidentally being shared by different targets.
