# Overview
This is an example of migrating a patternfly 5 application 6 with Goose and an update skill that leverages [semver-analyzer](https://github.com/shawn-hurley/semver-analyzer) and [frontend-analyzer-provider](https://github.com/shawn-hurley/frontend-analyzer-provider)

## Semver
[semver-analyzer](https://github.com/shawn-hurley/semver-analyzer) will look at the source code of 2 different releases of a framework and extract "migration concerns" in a deterministic manner, these concerns can then be codified into rules, for this use-case we will codify them into konveyor rules.
 * You can see the rules produced when we ran from patternfly "v5.4.0" to patternfly "v6.4.1":
    * [semver-generated-rules-pf5-to-pf6](semver-generated-rules-pf5-to-pf6)

## Frontend Analyzer Provider 
[frontend-analyzer-provider](https://github.com/shawn-hurley/frontend-analyzer-provider) provides improved capability to run konveyor rules against typescript and css resources.  This is a newer provider from the [nodejs provider of analyzer-lsp](https://github.com/konveyor/analyzer-lsp/blob/3e96e2cf5343f83bcf23155557be8fdedc1580d1/provider_container_settings.json#L61-L83).  

## How to run
### Prequisites
* Kantra needs to be installed with `java-external-provider` that is greater than 0.9.2, used a custom build binary from main as of April 10 2026.
* [frontend-analyzer-provider](https://github.com/shawn-hurley/frontend-analyzer-provider) needs to be built, used v0.0.4 (~April 9 2026)
* podman needs to be installed and running
### Run
1. `./goose.sh`
    * you can see the output as this ran in [migration-20260415-094525.log](migration-20260415-094525.log)

## Results
* The results of this migration can be viewed in this PR: https://github.com/jwmatthews/lightspeed-console/pull/1
    * That represents the PF6 changes the migration skill performed against the "pattern-fly-5" branch.
