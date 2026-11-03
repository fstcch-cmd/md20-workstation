[繁中](MAC.md) · [English](MAC.en.md) · [日本語](MAC.ja.md) · [한국어](MAC.ko.md)

# MD20 student guide: macOS

You need macOS 12 or later (Apple Silicon M1–M4 or Intel), at least 8 GB of free disk space and an internet connection. Macs have no CUDA, so MD20 computes on OpenCL or the CPU. That is slower than an NVIDIA laptop. **Use the classroom tier for class cases.**

## 1. Install (once, about 15–30 minutes)
1. Download `MD20-macOS-v0.1.0a9.zip` and double-click it in Downloads to unzip it. You get the folder `MD20-v0.1.0a9`.
2. Open Terminal (search for Terminal in Launchpad), paste the line below and press Enter.

```
bash ~/Downloads/MD20-v0.1.0a9/Install-MD20.command
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
- Use only letters and digits in the project name.
- **Plug the laptop in** and do not let it go to sleep.
- You can close Terminal halfway. **Type the last line again and it continues from where it stopped.**
- The results are in `MD20_Projects/first_case` inside your Documents folder. Open `report.html` there.

## 4. If something goes wrong
Run the line below and send a copy of the output to your instructor.
```
~/MD20/md20 doctor --no-benchmark
```
