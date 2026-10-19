using System;

class AveryPrintTests {
    static int checks;
    static void Check(bool ok){checks++;if(!ok)throw new Exception("Avery print permit case "+checks);}
    static void Main(){
        var permit=new DesktopRenderer.AveryPrintPermit(17,"private-nonce","exact-document");
        Check(!permit.Take(18,"private-nonce",1,true)); // Foreign isolated world.
        Check(!permit.Take(17,"foreign-nonce",1,true));
        Check(!permit.Take(17,"private-nonce",1,false)); // Retired/foreign child or opener.
        Check(!permit.Take(17,"private-nonce",0,true));
        Check(!permit.Take(17,"private-nonce",2,true)); // Out of order.
        Check(permit.Take(17,"private-nonce",1,true));
        Check(!permit.Take(17,"private-nonce",1,true)); // Replay consumed before UI.
        // Cancel is entirely native; a later deliberate activation may retry.
        Check(permit.Take(17,"private-nonce",2,true));
        Check(!permit.Take(17,"private-nonce",3,false));
        Check(permit.Take(17,"private-nonce",3,true));
        Check(permit.Identity=="exact-document"&&permit.Context==17);
        var invalid=new DesktopRenderer.AveryPrintPermit(0,"nonce","document");
        Check(!invalid.Take(0,"nonce",1,true));
        Console.WriteLine("{\"passed\":true,\"checks\":"+checks+",\"browser_launched\":false}");
    }
}
