[繁中](MAC.md) · [English](MAC.en.md) · [日本語](MAC.ja.md) · [한국어](MAC.ko.md)

Licence: real calculations need a licence file; see [UNLOCK.en.md](UNLOCK.en.md) to get and import it.

# MD20 student guide: macOS

You need macOS 12 or later (Apple Silicon M1–M4 or Intel), at least 8 GB of free disk space and an internet connection. Macs have no CUDA, so MD20 computes on OpenCL or the CPU. That is slower than an NVIDIA laptop. **Use the classroom tier for class cases.**

## 1. Install (once, about 15–30 minutes)
1. Download `MD20-macOS-v0.1.0a17.zip` and double-click it in Downloads to unzip it. You get the folder `MD20-v0.1.0a17`.
2. Open Terminal (search for Terminal in Launchpad), paste the line below and press Enter.

```
bash ~/Downloads/MD20-v0.1.0a17/Install-MD20.command
```
   - The installation is finished when Terminal ends with "完成 Done.". If you see an error, copy the text in Terminal and send it to your instructor.
   - The program is installed in the `MD20` folder in your home folder. You can delete the downloaded folder afterwards.
3. A new file, `MD20-GUI.command`, appears on the Desktop.

## 2. Every time you use it
- Graphical interface: double-click `MD20-GUI.command` on the Desktop, then open http://127.0.0.1:8020 in your browser. **Do not close the Terminal window while a calculation is running.** You can close the browser. Close the Terminal window when you are done.
- If macOS says the file cannot be opened the first time, right-click the file, choose "Open", then click "Open" again.
- Language: the language menu at the top right switches between English, 繁體中文, 日本語 and 한국어.
- To write a report while MD20 runs: the resource menu at the top right normally shows "Balanced (default)". Choose "Light: keep using the computer". The change applies from the next calculation step. When you are not using the computer, you can choose "Full speed: computer idle".
- Command line: type the line below in Terminal.

```
~/MD20/md20 doctor
```
The command line prints in Chinese. Look for the line 「選用 OpenMM 平台」 (OpenMM platform used). OpenCL means the graphics chip is in use. CPU also works, only more slowly.

```
~/MD20/md20 demo
```
This demo workflow does no real calculation. It finishes within 1 minute and produces a report. If it finishes, the installation works.

## 3. Your first real case (trypsin and benzamidine)
```
cd ~/Desktop
~/MD20/md20 pipeline example > trypsin.json
sed -i '' 's/"tier": "teaching"/"tier": "classroom"/' trypsin.json
~/MD20/md20 pipeline run trypsin.json --project first_case
```
- The third line changes the tier to classroom (2 ns). On a Mac this should take about 2–4 hours. This is an estimate and has not been measured yet.
- The times above are for one trajectory per system. Each system now runs 3 independent replicas by default, so the molecular dynamics part takes about 3 times as long (SMD and umbrella sampling do not change), and the report can show standard deviations. The replica plan and the estimated time appear when you start. To only walk through the workflow once, change `"replicas": 3` to `1`. The report then marks every place "single trajectory, uncertainty cannot be estimated".
- Use only letters and digits in the project name.
- **Plug the laptop in** and do not let it go to sleep.
- You can close Terminal halfway. **Type the last line again and it continues from where it stopped.**
- The results are in `MD20_Projects/first_case` inside your Documents folder. Open `report.html` there.

## 4. Back to an old workflow, choosing ligands for binding free energy
- **Found again after closing**: when you start `MD20-GUI.command` again, Recent workflows on the home page lists every workflow saved in Documents/MD20_Projects, newest first, with a search box. For one marked Not finished or interrupted last time, open it and press Start or continue to go on from where it stopped; a finished one opens its report.
- **Choose where projects are saved, open any project folder**: under Projects folder on the home page, paste a path or press Browse…. After Save projects here, new projects go there (for example an external drive with more space), and MD20 and the command line use that folder next time. To open a project folder (or a workflow folder) someone gave you, choose it and press Open this project or workflow. Recent folders are listed below; click one to switch back.
- **One ligand from the all-ligands system (for example teaching mode 1, hsieh2024)**: on the workflow page open Binding free energy (SMD and umbrella sampling), tick one ligand and press Compute the selected ligands. The other ligands stay in the pocket while it is pulled; the report labels the result With the other ligands, and it cannot be compared directly with binding alone.
- **More after the report**: tick another ligand there and press Compute the selected ligands; finished ones are not recomputed. To run the same ligand once more with a new random seed, tick it and press One more SMD run for the selected ligand; the report lists each run and their mean.
- Press Rebuild the report to see the combined report at once. Each ligand takes hours of SMD and umbrella sampling, so keep the laptop on power.

## 5. A peptide as the ligand (paste the sequence)
1. **Install the folding tool first (once, at home before class)**: double-click `Install-Folding.command` in the unzipped folder. It downloads PyTorch and the model weights, several GB in total, in about 20–60 minutes, and then folds one test peptide. It is installed when you see Done at the end. You can also press Install now on the Computer status page of the interface.
2. In quick mode, paste the sequence into the ligand box with a name in front:
   ```
   MEL GIGAVLKVLTTGLPALISWIKRKRQQ
   ```
   A sequence alone also works; it is named PEP. You no longer need `peptide:`.
3. For a peptide of 10 or more residues, "Fold this peptide first" is ticked for you: the program predicts its structure, then docks it and runs MD. Untick it to skip folding. A peptide shorter than 10 residues usually has no fixed structure on its own, so it is not folded and docking changes its shape instead.
4. If the prediction confidence is low (pLDDT below 50) or no folding tool is installed, the workflow stops at the folding step and lists what you can do: install the tool, upload a structure from AlphaFold Server, or skip folding.
5. If a sequence contains only the letters C, N, P, S, F and I (for example `CCCCCN`), it could also be SMILES, so the program asks you to put `peptide:` or `smiles:` in front of it.

## 6. Coarse-grained Martini 3 (professional mode, optional)
Use coarse-graining for events that take microseconds or longer: how a membrane protein sits in the bilayer, how a peptide lands on a membrane, how the membrane itself changes. About four heavy atoms become one bead and the time step is 20 fs, so the same laptop runs tens of times longer than all-atom.
1. **Install the tools first (once)**: on the Computer status page of the interface, press Install now in the coarse-grained row, or run `~/MD20/md20 setup-cg --yes`. It installs martinize2, insane and martini_openmm and downloads the Martini 3 force-field files, then shows the finished message.
2. In the Membrane group of professional mode, set Resolution to Coarse-grained Martini 3, then choose the system: membrane protein (enter a PDB ID), membrane surface (paste a peptide sequence in the ligand box), bilayer only, or no membrane (protein in water).
3. The length follows the usual production length setting; over 1 µs asks you to confirm first.
4. Coarse-grained runs do no docking and no binding free energy, and small-molecule ligands are left out. The report's numbers are bead-level, not all-atom, and the report says so.

## 7. If something goes wrong
Run the line below and send a copy of the output to your instructor.
```
~/MD20/md20 doctor --no-benchmark
```
