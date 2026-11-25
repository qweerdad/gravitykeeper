# GitHub release checklist

## Local candidate

- [ ] Review English and Chinese docs, tested compatibility and unofficial status.
- [ ] Run Windows tests. Retain separate synthetic and real read-only acceptance results.
- [ ] Build Windows x64. Extract, hash-check and launch the two EXEs with their bundled runtime.
- [ ] Audit tracked files, index, Git history and the final ZIP.
- [ ] Capture and review actual desktop screenshots using only the fictional demo.
- [ ] Check bundled runtime notices and SHA-256. Note the signature status in release notes.
- [ ] Review the local commit and confirm there is no configured remote.

## After the owner authorizes public publication

- [ ] Confirm the repository name and project description and review third-party distribution notices again if the runtime changes.
- [ ] Create the public repository and push the reviewed history only.
- [ ] Enable private vulnerability reporting and review Actions permissions.
- [ ] Verify the hosted workflow result before marking the release as supported.
- [ ] Create the release and upload only the portable program ZIP and its SHA-256 sidecar.
- [ ] Download the public artifacts and compare the hash to the locally accepted build.
