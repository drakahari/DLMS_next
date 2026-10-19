using System;
using System.Threading.Tasks;
using System.Windows.Forms;

class AveryStackTests {
    static int checks;
    static void Check(bool ok){checks++;if(!ok)throw new Exception("Avery stack case "+checks);}
    [STAThread] static void Main(){
        // Never Show a window, initialize WebView2, or send native input.
        using(var parent=new Form()) using(var browser=new Panel()) using(var cover=new Panel()) {
            parent.Controls.Add(browser);parent.Controls.Add(cover);
            Control preview=new Panel();parent.Controls.Add(preview);
            int retirements=0;
            Func<Task> retire=()=>{retirements++;if(preview!=null){preview.Dispose();preview=null;}return Task.FromResult(0);};
            Func<bool,bool,bool,bool,string> apply=(shown,visible,current,ready)=>
                DesktopRenderer.ApplyServerCoverStack(browser,cover,preview,shown,visible,current,ready,retire,()=>true).GetAwaiter().GetResult();
            var original=preview;
            for(int n=0;n<20;n++) {
                browser.BringToFront();
                Check(apply(false,true,true,true)=="preview");
                Check(parent.Controls.GetChildIndex(preview)==0);
                Check(Object.ReferenceEquals(original,preview)&&!preview.IsDisposed&&retirements==0);
            }
            Check(apply(true,true,true,true)=="cover");
            Check(retirements==1&&preview==null&&original.IsDisposed);
            Check(parent.Controls.GetChildIndex(cover)==0);
            Check(apply(false,true,false,false)=="source");
            Check(preview==null&&retirements==1&&parent.Controls.GetChildIndex(browser)==0);
            preview=new Panel();parent.Controls.Add(preview);
            Check(apply(false,false,true,true)=="source");
            Check(preview==null&&retirements==2);
            // Invalidated navigation/ownership must retire, not resurrect on uncover.
            preview=new Panel();parent.Controls.Add(preview);
            Check(apply(false,true,false,true)=="source");
            Check(preview==null&&retirements==3);
            Check(apply(false,true,false,false)=="source"&&retirements==3);
            // Ordinary refresh during asynchronous preparation preserves its lease.
            preview=new Panel();parent.Controls.Add(preview);original=preview;
            Check(apply(false,true,true,false)=="source");
            Check(Object.ReferenceEquals(original,preview)&&retirements==3);
            Check(apply(true,true,true,false)=="cover");
            Check(preview==null&&retirements==4);
            // An old invalid-owner uncover waits while a newer genuine cover wins.
            preview=new Panel();parent.Controls.Add(preview);
            var delayed=new TaskCompletionSource<int>();int serial=1;
            var old=DesktopRenderer.ApplyServerCoverStack(browser,cover,preview,false,true,false,true,
                ()=>delayed.Task,()=>serial==1);
            Check(!old.IsCompleted);
            serial=2;
            Check(DesktopRenderer.ApplyServerCoverStack(browser,cover,preview,true,true,true,true,
                retire,()=>serial==2).GetAwaiter().GetResult()=="cover");
            delayed.SetResult(0);
            Check(old.GetAwaiter().GetResult()=="superseded");
            Check(parent.Controls.GetChildIndex(cover)==0&&preview==null&&retirements==5);
            // Navigation/close invalidation also prevents a pending reveal applying.
            delayed=new TaskCompletionSource<int>();bool currentOwner=true;
            var pending=DesktopRenderer.ApplyServerCoverStack(browser,cover,null,true,true,false,false,
                ()=>delayed.Task,()=>currentOwner);
            currentOwner=false;browser.BringToFront();delayed.SetResult(0);
            Check(pending.GetAwaiter().GetResult()=="superseded");
            Check(parent.Controls.GetChildIndex(browser)==0);
        }
        Console.WriteLine("{\"passed\":true,\"checks\":"+checks+",\"browser_launched\":false,\"window_shown\":false}");
    }
}
