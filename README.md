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

1. Add `k`, `kninja` and `pandoc-tangle` (optional) as submodules:

   ```
   git submodule add https://github.com/kframework/k           ext/k
   git submodule add https://github.com/nishantjr/kninja       ext/kninja
   git submodule add https://github.com/ehildenb/pandoc-tangle ext/pandoc-tangle
   ```

2. Add a script `lib/build.py` (we call this the "generator" script):

   ```
   #!/usr/bin/env python3

   from kninja import *
   import sys
   import os.path

   # Project Definition
   # ==================

   proj = KProject()
   mydef = proj.source('mydef.md') \
               .then(proj.tangle().output(proj.tangleddir('mydef.k')))
               .then(proj.kompile(backend = 'java') \
                         .variables(directory = proj.builddir('mydef')))

   def mydef_test(file, expected):                                                                              
       proj.source(file) \
           .then(mydef.krun()) \
           .then(proj.check(proj.source(expected))
                        .variables(flags = '--ignore-all-space')) \
           .default()

   mydef_test('t/foo.mydef',  't/foo.mydef.expected')
   mydef_test('t/bar.mydef',  't/bar.mydef.expected')
   mydef_test('t/buzz.mydef', 't/buzz.mydef.expected')
   ```

3. Add a script (typically called `build`) at the top-level of your project:

   ```
   #!/usr/bin/env bash

   set -eu
   base="$(cd "$(dirname "$0")"; pwd)"
   type -t ninja > /dev/null || fail "`ninja-build` not available. Giving up."
   git submodule update --init $base/ext/
   export PYTHONPATH="$base/ext/"
   python3 lib/build.py
   exec ninja -f .build/generated.ninja "$@"
   ```

   Make executable: `chmod +x lib/build.py`

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
