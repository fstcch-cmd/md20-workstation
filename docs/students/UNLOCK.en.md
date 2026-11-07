[繁中](UNLOCK.md) · [English](UNLOCK.en.md) · [日本語](UNLOCK.ja.md) · [한국어](UNLOCK.ko.md)

# Get and import your MD20 licence

The MD20 source code is public, but real calculations (docking, system building, molecular dynamics, binding free energy, peptide folding) need a licence file signed by HCC Lab. Without one, the computer check (`doctor`), the demo (`demo`), reports and the graphical interface still work.

## 1. Get the machine code
1. After installing, double-click `MD20-Unlock.cmd` on the desktop (`MD20-Unlock.command` on a Mac).
2. The first line in the window is the machine code of this computer, something like `3F9A-07C2-B15D-6E48`. It is already copied to the clipboard.
3. Send the machine code to your instructor. They sign a licence that works only on this computer.
4. You can also type `%LOCALAPPDATA%\MD20\md20.cmd license machine`. The "MD20 licence needed" card at the top of every page in the graphical interface shows it as well.

## 2. Import the licence file
Your instructor sends you a file ending in `.md20license`. Use any one of these:
- **Drag and drop**: drag the file onto the `MD20-Unlock.cmd` icon on the desktop.
- **Double-click**: double-click `MD20-Unlock.cmd` and choose the file in the window that opens.
- **Graphical interface**: press "Import licence file" on the card at the top of the page and choose the file.

When you see "Licence installed", you are done. There is nothing more to do until the licence expires.

## 3. Common messages
| Message | Meaning | What to do |
|---|---|---|
| This computer has no MD20 licence yet | Nothing imported yet | Get and import it as above |
| This licence is bound to another computer | It is someone else's file | Send this computer's machine code to your instructor for a new one |
| The licence expired | Past the end date | Ask your instructor to renew it, then import the new file |
| The signature of the licence file is not valid | The file was changed or damaged | Ask for a fresh copy; do not open or save it in a text editor |

The licence file is personal. Do not pass it on or post it anywhere public. Files MD20 writes record the licence id and your name so they can be traced.

Command line: `md20 license status` shows the state and `md20 license install FILE` imports a file. Without a licence, calculation commands stop with exit code 13 and explain why.
