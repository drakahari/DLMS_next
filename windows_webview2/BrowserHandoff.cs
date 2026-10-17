// Windows association handoff through the existing desktop Explorer, not through
// the renderer's isolated environment or kill-on-close Job. No browser executable,
// profile, cookies, credentials, custom arguments or page-visible API is used.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;

static class BrowserHandoff {
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern bool SetDllDirectory(string path);
    [DllImport("user32.dll")] static extern IntPtr GetShellWindow();
    [DllImport("user32.dll",SetLastError=true)]
    static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);

    [ComImport,Guid("9BA05972-F6A8-11CF-A442-00A0C90A8F39")]
    class ShellWindows {}
    [ComImport,Guid("85CB6900-4D95-11CF-960C-0080C7F4EE85"),InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    interface Windows {
        [return:MarshalAs(UnmanagedType.IDispatch)] object FindWindowSW(
            [MarshalAs(UnmanagedType.Struct)] ref object location,
            [MarshalAs(UnmanagedType.Struct)] ref object root,int kind,out int hwnd,int options);
    }
    [ComImport,Guid("6D5140C1-7436-11CE-8034-00AA006009FA"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface Services {
        [return:MarshalAs(UnmanagedType.Interface)] object QueryService(ref Guid service,ref Guid iid);
    }
    [ComImport,Guid("000214E2-0000-0000-C000-000000000046"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface Browser {
        void GetWindow(); void ContextSensitiveHelp(); void InsertMenus();
        void SetMenu(); void RemoveMenus(); void SetStatusText(); void EnableModeless();
        void TranslateAccelerator(); void BrowseObject(); void GetViewStateStream();
        void GetControlWindow(); void SendControlMessage();
        [return:MarshalAs(UnmanagedType.Interface)] View QueryActiveShellView();
    }
    [ComImport,Guid("000214E3-0000-0000-C000-000000000046"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface View {
        void GetWindow(); void ContextSensitiveHelp(); void TranslateAccelerator();
        void EnableModeless(); void Activate(); void Refresh(); void CreateWindow();
        void DestroyWindow(); void GetInfo(); void AddPropertyPages(); void SaveState(); void SelectItem();
        [return:MarshalAs(UnmanagedType.Interface)] object GetItemObject(uint aspect,ref Guid iid);
    }
    [ComImport,Guid("E7A1AF80-4D96-11CF-960C-0080C7F4EE85"),InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    interface FolderView {
        object Application { [return:MarshalAs(UnmanagedType.IDispatch)] get; }
    }
    [ComImport,Guid("A4C6892C-3BA9-11D2-9DEA-00C04FB16162"),InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    interface Dispatch {
        void ShellExecute([MarshalAs(UnmanagedType.BStr)] string file,
            [MarshalAs(UnmanagedType.Struct)] object arguments,
            [MarshalAs(UnmanagedType.Struct)] object directory,
            [MarshalAs(UnmanagedType.Struct)] object operation,
            [MarshalAs(UnmanagedType.Struct)] object show);
    }

    internal static string Target(string value) {
        Uri url;
        if(String.IsNullOrEmpty(value)||value.Length>8192||value.IndexOf('\\')>=0)
            throw new ArgumentException("External URL refused");
        foreach(char ch in value)if(ch<32||ch==127)throw new ArgumentException("External URL refused");
        if(!Uri.TryCreate(value,UriKind.Absolute,out url)||
            (url.Scheme!="http"&&url.Scheme!="https")||url.UserInfo.Length!=0||
            String.IsNullOrEmpty(url.Host)||url.IsLoopback||
            url.Host.TrimEnd('.').Equals("localhost",StringComparison.OrdinalIgnoreCase)||
            url.Host.TrimEnd('.').EndsWith(".localhost",StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("External URL refused");
        // Preserve the exact previously confirmed encoded destination.
        return value;
    }

    static Dispatch Desktop(List<object> held) {
        IntPtr desktop=GetShellWindow();uint desktopPid;
        if(desktop==IntPtr.Zero||GetWindowThreadProcessId(desktop,out desktopPid)==0)
            throw new InvalidOperationException("Desktop shell unavailable");
        // Pin the process while resolving the existing desktop's interfaces.
        using(var process=Process.GetProcessById((int)desktopPid)) {
            if(process.SessionId!=Process.GetCurrentProcess().SessionId||process.HasExited)
                throw new InvalidOperationException("Desktop session mismatch");
            IntPtr token;
            if(!OpenProcessToken(process.Handle,8,out token))throw new InvalidOperationException("Desktop user unavailable");
            try {
                using(var desktopUser=new WindowsIdentity(token))using(var caller=WindowsIdentity.GetCurrent())
                    if(desktopUser.User!=caller.User)throw new InvalidOperationException("Desktop user mismatch");
            }finally{CloseHandle(token);}
            string expected=System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),"explorer.exe");
            if(!String.Equals(process.MainModule.FileName,expected,StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Unexpected desktop shell");
            var windows=(Windows)new ShellWindows();held.Add(windows);
            object location=0,root=null;int hwnd;
            object located=windows.FindWindowSW(ref location,ref root,8,out hwnd,1);held.Add(located);
            if(located==null||unchecked((uint)hwnd)!=unchecked((uint)desktop.ToInt64()))
                throw new InvalidOperationException("Desktop window mismatch");
            Guid service=new Guid("4C96BE40-915C-11CF-99D3-00AA004AE837"),iid=typeof(Browser).GUID;
            var browser=(Browser)((Services)located).QueryService(ref service,ref iid);held.Add(browser);
            var view=browser.QueryActiveShellView();held.Add(view);
            iid=new Guid("00020400-0000-0000-C000-000000000046");
            var folder=(FolderView)view.GetItemObject(0,ref iid);held.Add(folder);
            object application=folder.Application;held.Add(application);
            uint nowPid;
            if(process.HasExited||GetShellWindow()!=desktop||GetWindowThreadProcessId(desktop,out nowPid)==0||nowPid!=desktopPid)
                throw new InvalidOperationException("Desktop shell changed");
            return (Dispatch)application;
        }
    }

    internal static int Run() {
        var held=new List<object>();
        try {
            // This affects only this short helper, never Python/the renderer.
            if(!SetDllDirectory(null))throw new InvalidOperationException("Helper DLL search unavailable");
            var text=new System.Text.StringBuilder();int ch;
            while((ch=Console.In.Read())!=-1&&ch!='\n') {
                if(text.Length>=8192)throw new ArgumentException("External URL refused");
                text.Append((char)ch);
            }
            if(ch!='\n')throw new ArgumentException("External URL incomplete");
            string url=Target(text.ToString());
            Desktop(held).ShellExecute(url,"",Environment.GetFolderPath(Environment.SpecialFolder.System),"open",1);
            Console.WriteLine("accepted");return 0;
        }catch(Exception error) {
            // URL/profile/exception text is deliberately excluded.
            Console.Error.WriteLine("Browser handoff not confirmed (0x"+error.HResult.ToString("X8")+").");return 3;
        }finally {
            var released=new HashSet<object>();
            for(int index=held.Count-1;index>=0;index--) {
                object item=held[index];
                if(item!=null&&released.Add(item)&&Marshal.IsComObject(item)) {
                    try{Marshal.FinalReleaseComObject(item);}catch{}
                }
            }
        }
    }
}
