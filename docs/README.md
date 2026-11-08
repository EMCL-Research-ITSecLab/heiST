# heiST documentation

Start with the guide matching your task. Production installation and upgrades
remain gated; see the current [acceptance status](validation/rollouts.md).

| Task | Guide |
|---|---|
| Manage users, exercises and running instances | [Administrator guide](administration/README.md) |
| Plan an update or recover an interrupted rollout | [Updates and recovery](administration/UPDATES.md) |
| Configure the separate archive VM | [Log archiving](administration/LOG-ARCHIVING.md) |
| Build offline browser runtimes | [Offline runtime](administration/OFFLINE-RUNTIME.md) |
| Run development tests | [Testing](testing/README.md) |
| Review the complete acceptance concept | [Test concept](testing/TEST-CONCEPT.md) |
| Run a disposable local appliance | [Local appliance](testing/LOCAL-APPLIANCE.md) |
| Review all UI pages and regenerate screenshots | [UI verification](testing/UI-VERIFICATION.md) · [Screenshot gallery](../assets/screenshots/README.md) |
| Maintain the application | [Development guide](development/README.md) · [Architecture](development/ARCHITECTURE.md) |
| Work on the frontend or browser API | [Frontend](development/FRONTEND.md) · [API contracts](development/WEB-API.md) |
| Convert or build exercise images | [Operator tools](operator-tools/README.md) |

`validation/` records dated fixture results, including failures and recovery. It is
historical evidence, not an installation recipe or approval to deploy production.
Generated release bundles, VM images and private diagnostics belong outside this
repository under `/mnt/data/heist-builds`.
