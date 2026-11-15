; 图片合并为 PDF —— Inno Setup 安装脚本
#define MyAppName "Document Tool"
#define MyAppVersion "1.0"
#define MyAppExeName "Document Tool.exe"
#define MyAppPublisher "PDF Producer"

[Setup]
AppId={{B7B0F3C2-6E1A-4A8E-9D7B-2C5E8F1A9D43}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PDFProducer
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=Document Tool 安装程序 1.0
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "dist\Document Tool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
SetupAppTitle=安装程序
SetupWindowTitle=安装 - %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=即将在您的电脑上安装 [name] %1。%n%n建议关闭其他程序后继续，点击“下一步”。
WizardSelectDirDesc=选择安装位置
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹。
SelectDirBrowseLabel=点击“下一步”继续；如需选择其他文件夹，点击“浏览”。
WizardReadyDesc=准备安装
ReadyLabel1=准备就绪
ReadyLabel2a=点击“安装”开始安装；如需检查或更改设置，点击“上一步”。
WizardInstalling=正在安装
InstallingLabel=正在安装 [name]，请稍候……
WizardFinished=完成
FinishedHeadingLabel=[name] 安装完成
FinishedLabel=安装程序已把 [name] 安装到您的电脑上。%n%n点击“完成”退出安装程序。
FinishedRestartLabel=需要重启电脑才能完成安装。%n%n点击“完成”立即重启。
WizardUninstalling=正在卸载
ButtonNext=下一步(&N) >
ButtonBack=< 上一步(&B)
ButtonCancel=取消(&C)
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonClose=关闭
ButtonYes=是(&Y)
ButtonNo=否(&N)
ButtonOK=确定
ButtonUninstall=卸载(&U)
CreateDesktopIcon=创建桌面快捷方式(&D)
ConfirmUninstall=确定要彻底卸载 %1 及其所有组件吗？
UninstalledAll=%1 已成功卸载。
UninstalledMost=卸载完成。%n%n部分文件需要手动删除。
UninstallStatusLabel=正在卸载 %1，请稍候……