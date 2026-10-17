// Public WebView2 controller ownership, without the SDK WinForms tab wrapper.
using System;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

sealed class BrowserSurface : Control {
    CoreWebView2Controller controller;
    Task initialization;
    bool retiring,movingFocus;
    bool externalDrop;
    Color background=Color.White;
    double zoom=1.0;
    public event Action<CoreWebView2MoveFocusReason> FocusBoundary;
    public CoreWebView2 CoreWebView2 {get{return controller==null?null:controller.CoreWebView2;}}
    public double ZoomFactor {get{return controller==null?zoom:controller.ZoomFactor;}set{if(controller!=null)controller.ZoomFactor=value;zoom=value;}}
    public Color DefaultBackgroundColor {get{return background;}set{background=value;BackColor=value;if(controller!=null)controller.DefaultBackgroundColor=value;}}
    public bool AllowExternalDrop {get{return externalDrop;}set{externalDrop=value;if(controller!=null)controller.AllowExternalDrop=value;}}

    public BrowserSurface() {TabStop=true;SetStyle(ControlStyles.Selectable,true);}
    public Task EnsureCoreWebView2Async(CoreWebView2Environment environment) {
        if(retiring||IsDisposed)throw new ObjectDisposedException("BrowserSurface");
        if(initialization==null)initialization=CreateController(environment);
        return initialization;
    }
    async Task CreateController(CoreWebView2Environment environment) {
        var created=await environment.CreateCoreWebView2ControllerAsync(Handle);
        if(retiring||IsDisposed){created.Close();throw new ObjectDisposedException("BrowserSurface");}
        controller=created;
        controller.AllowExternalDrop=externalDrop;controller.DefaultBackgroundColor=background;
        controller.ZoomFactor=zoom;controller.Bounds=ClientRectangle;controller.IsVisible=Visible;
        controller.MoveFocusRequested+=(sender,args)=> {
            if(args.Reason!=CoreWebView2MoveFocusReason.Next&&args.Reason!=CoreWebView2MoveFocusReason.Previous)return;
            args.Handled=true;
            var handler=FocusBoundary;if(!retiring&&handler!=null)handler(args.Reason);
        };
        NotifyPosition();
    }
    public void NotifyPosition() {if(controller!=null&&!retiring)controller.NotifyParentWindowPositionChanged();}
    protected override void OnResize(EventArgs args) {base.OnResize(args);if(controller!=null&&!retiring){controller.Bounds=ClientRectangle;NotifyPosition();}}
    protected override void OnLocationChanged(EventArgs args) {base.OnLocationChanged(args);NotifyPosition();}
    protected override void OnParentChanged(EventArgs args) {base.OnParentChanged(args);NotifyPosition();}
    protected override void OnVisibleChanged(EventArgs args) {base.OnVisibleChanged(args);if(controller!=null&&!retiring)controller.IsVisible=Visible;}
    protected override bool ProcessDialogKey(Keys keys) {
        // Let Chromium process Tab and arrow navigation within its document.
        // At the boundary its public native event transfers focus to Qt.
        Keys code=keys&Keys.KeyCode;
        if((keys&(Keys.Alt|Keys.Control))==0&&(code==Keys.Tab||code==Keys.Left||code==Keys.Right||code==Keys.Up||code==Keys.Down))return false;
        return base.ProcessDialogKey(keys);
    }
    protected override void OnGotFocus(EventArgs args) {
        base.OnGotFocus(args);
        if(!movingFocus&&controller!=null&&!retiring)controller.MoveFocus(CoreWebView2MoveFocusReason.Programmatic);
    }
    public new bool Focus() {return Focus(CoreWebView2MoveFocusReason.Programmatic);}
    public bool Focus(CoreWebView2MoveFocusReason reason) {
        if(retiring||controller==null||!CanFocus)return false;
        movingFocus=true;
        try {bool focused=base.Focus();controller.MoveFocus(reason);return focused;}
        finally{movingFocus=false;}
    }
    protected override void Dispose(bool disposing) {
        try {if(!retiring){retiring=true;var owned=controller;controller=null;if(owned!=null)owned.Close();}}
        finally{base.Dispose(disposing);}
    }
}
