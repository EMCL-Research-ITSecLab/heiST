# Add scheduled platform upgrades with verified checkpoints and recovery

Target `feat/local-testing-and-updates` for this stacked PR, or merge its base
first. Production remains on main; no production deployment is included.

heiST's installer combined dependency bootstrapping with its interface, generated
commands by scanning scripts, and offered destructive uninstall behavior. This
change introduces an explicit `heist` CLI, separates installer bootstrap/interface,
shares database configuration and SSH helpers, bounds cleanup retries, propagates
worker failures and retires the destructive uninstall script. Generated package
metadata is removed from Git. Existing service entry points remain supported.

Scheduled updates now plan immutable releases, gate writers/public web traffic,
verify SQL and complete infrastructure VM checkpoints, deploy backend/web source,
run checksum-bound transactional migrations, and check health plus protected
student/grade data before committing. Durable journals distinguish recovery before
commit from service completion after writers may resume. Interrupted Proxmox jobs
have explicit task adoption and failed-restore retry commands. Deliberate rollback
requires version confirmation and first captures a new safety checkpoint.

Public web deployments exclude test/mocks and regenerate existing Composer
autoload metadata without installing dependencies or running plugins/scripts.
No application framework, dependency or library is added.

Validation: 132 Python tests passed in the disposable appliance with real
PostgreSQL and privileged isolation checks; 142 PHP tests passed with 540
assertions. Complete update, real three-VM failure recovery, deliberate rollback,
postcommit resume, restore of the newer SQL safety dump, and a real web-VM
reboot under maintenance passed. This fixture
is not a restored production clone.

See `docs/UPDATES.md` for configuration, limitations and recovery commands, and
`docs/ROLLOUT-VALIDATION.md` for exact validation evidence and remaining production
gates. The fresh installer still needs a separate host checkpoint/resume design;
this release controller does not make installation transactional.
