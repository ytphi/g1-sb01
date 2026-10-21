# Where this folder comes from

Copied from Prof. Yutong Liu's repository
[ytphi/g1-qtm-teleop](https://github.com/ytphi/g1-qtm-teleop), commit `171d0c7`
(2026-10-13, "Fix GMR pelvis tilt; add --float-base dry-run preview; wired QTM config"),
so it can be changed and pulled to the lab computer with the rest of this repository.
Her README.md in this folder is unchanged and is the setup guide.

Changes from her version:
- `config/teleop.yaml`: `robot.network_interface` is `enp2s0`, the lab computer's port to the G1 (hers was `eno0`).
- `config/teleop_laptop.yaml` (added): `teleop.yaml` at 50 updates a second instead of 100, for recording on
  laptops, which can't keep 100 (takes would play back too fast). See the note at its top.

Run everything from inside this folder (`cd mocap`): her scripts use paths relative to it.
`bash setup.sh` clones GMR into `mocap/GMR/`, which git ignores; the lab computer runs it once itself.

Note: this folder has its own `teleop/` package, a different one from the repository's top-level `teleop/`.
Run the two as separate programs; importing both into one program would collide.
