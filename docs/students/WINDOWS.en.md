[繁中](WINDOWS.md) · [English](WINDOWS.en.md) · [日本語](WINDOWS.ja.md) · [한국어](WINDOWS.ko.md)

# MD20 student guide: Windows

You need Windows 10 or 11, at least 8 GB of free disk space and an internet connection. If the computer has an NVIDIA graphics card, MD20 uses the GPU (CUDA) automatically. Without one it still runs on OpenCL or the CPU, only more slowly.

## 1. Install (once, about 15–30 minutes)
1. Download `MD20-Windows-v0.1.0a14.zip` from the page your instructor gave you.
2. Right-click the file and choose "Extract All".
3. Open the extracted folder and double-click `Install-MD20.cmd`.
   - If a blue "Windows protected your PC" window appears, click "More info" and then "Run anyway".
   - The installation is finished when the window ends with "完成" (Done). If you see an error, take a photo of the whole window and send it to your instructor.
4. A new file, `MD20-GUI.cmd`, appears on the desktop.

## 2. Every time you use it
- Graphical interface: double-click `MD20-GUI.cmd` on the desktop. Your browser opens http://127.0.0.1:8020 . **Do not close the black window while a calculation is running.** You can close the browser. Close the black window when you are done.
- Language: the language menu at the top right switches between English, 繁體中文, 日本語 and 한국어.
- To write a report while MD20 runs: the resource menu at the top right normally shows "Balanced (default)". Choose "Light: keep using the computer". The change applies from the next calculation step. When you are not using the computer, you can choose "Full speed: computer idle".
- Command line: press `Win + R`, type `cmd`, press Enter, then type the line below.

```
%LOCALAPPDATA%\MD20\md20.cmd doctor
```
The command line prints in Chinese. Look for the line 「選用 OpenMM 平台」 (OpenMM platform used). CUDA or OpenCL means the graphics card is in use. CPU means it is not. MD20 still runs, only more slowly.

```
%LOCALAPPDATA%\MD20\md20.cmd demo
```
This demo workflow does no real calculation. It finishes within 1 minute and produces a report. If it finishes, the installation works.

## 3. Your first real case (trypsin and benzamidine)
```
cd %USERPROFILE%\Desktop
%LOCALAPPDATA%\MD20\md20.cmd pipeline example > trypsin.json
notepad trypsin.json
%LOCALAPPDATA%\MD20\md20.cmd pipeline run trypsin.json --project first_case
```
- The third line opens Notepad. Change `"tier": "teaching"` to `"tier": "classroom"` (2 ns), save the file and close Notepad.
- On an RTX 4060 laptop, classroom took 76.5 minutes (measured). If you leave it at teaching (10 ns), it takes about 3 hours (estimate). Without an NVIDIA graphics card it is much slower, so use classroom.
- Use only letters and digits in the project name. A Chinese name becomes a folder name made of unreadable codes.
- **Plug the laptop in.** On battery the calculation pauses automatically.
- You can close the window halfway. **Type the last line again and it continues from where it stopped.**
- The results are in `MD20_Projects\first_case` inside your Documents folder. Open `report.html` there.

## 4. Back to an old workflow, choosing ligands for binding free energy
- **Found again after closing**: when you start `MD20-GUI.cmd` again, Recent workflows on the home page lists every workflow saved in Documents\MD20_Projects, newest first, with a search box. For one marked Not finished or interrupted last time, open it and press Start or continue to go on from where it stopped; a finished one opens its report.
- **Choose where projects are saved, open any project folder**: under Projects folder on the home page, paste a path or press Browse…. After Save projects here, new projects go there (for example drive D: with more space), and MD20 and the command line use that folder next time. To open a project folder (or a workflow folder) someone gave you, choose it and press Open this project or workflow. Recent folders are listed below; click one to switch back.
- **One ligand from the all-ligands system (for example teaching mode 1, hsieh2024)**: on the workflow page open Binding free energy (SMD and umbrella sampling), tick one ligand and press Compute the selected ligands. The other ligands stay in the pocket while it is pulled; the report labels the result With the other ligands, and it cannot be compared directly with binding alone.
- **More after the report**: tick another ligand there and press Compute the selected ligands; finished ones are not recomputed. To run the same ligand once more with a new random seed, tick it and press One more SMD run for the selected ligand; the report lists each run and their mean.
- Press Rebuild the report to see the combined report at once. Each ligand takes hours of SMD and umbrella sampling, so keep the laptop on power.

## 5. A peptide as the ligand (paste the sequence)
1. **Install the folding tool first (once, at home before class)**: double-click `Install-Folding.cmd` in the unzipped folder. It downloads PyTorch and the model weights, several GB in total, in about 20–60 minutes, and then folds one test peptide. It is installed when you see Done at the end. You can also press Install now on the Computer status page of the interface.
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
1. **Install the tools first (once)**: on the Computer status page of the interface, press Install now in the coarse-grained row, or run `%LOCALAPPDATA%\MD20\md20.cmd setup-cg --yes`. It installs martinize2, insane and martini_openmm and downloads the Martini 3 force-field files, then shows the finished message.
2. In the Membrane group of professional mode, set Resolution to Coarse-grained Martini 3, then choose the system: membrane protein (enter a PDB ID), membrane surface (paste a peptide sequence in the ligand box), bilayer only, or no membrane (protein in water).
3. The length follows the usual production length setting; over 1 µs asks you to confirm first.
4. Coarse-grained runs do no docking and no binding free energy, and small-molecule ligands are left out. The report's numbers are bead-level, not all-atom, and the report says so.

## 7. If something goes wrong
Run the line below and send a photo or a copy of the output to your instructor.
```
%LOCALAPPDATA%\MD20\md20.cmd doctor --no-benchmark
```
