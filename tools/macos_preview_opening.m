// Controlled downloaded/quarantined preview opening check. No installed-app paths,
// quarantine removal, global trust changes, elevation or arbitrary UI actions.
// Compile after review: clang -fobjc-arc -framework AppKit -framework CoreServices
//   -framework ApplicationServices tools/macos_preview_opening.m -o <task cache>/opening
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <CoreServices/CoreServices.h>
#include <sys/stat.h>
#include <sys/xattr.h>
#include <errno.h>
#include <unistd.h>

static NSString * const PreviewID = @"io.github.drakahari.DLMSDesktop.MacPreview";
static NSString * const AgentID = @"io.github.drakahari.DLMSDesktop.PreviewOpeningCheck";
static NSString * const AgentName = @"DLMS Mac Preview Download Check";
static NSDictionary *Config;
static NSString *Action;
static BOOL FinderTextValues = NO;

static id JSONValue(id value) {
    if ([value isKindOfClass:NSURL.class]) return [value absoluteString];
    if ([value isKindOfClass:NSDate.class]) return @([value timeIntervalSince1970]);
    if ([value isKindOfClass:NSDictionary.class]) {
        NSMutableDictionary *result = [NSMutableDictionary dictionary];
        for (id key in value) result[[key description]] = JSONValue(value[key]) ?: NSNull.null;
        return result;
    }
    if ([value isKindOfClass:NSArray.class]) {
        NSMutableArray *result = [NSMutableArray array];
        for (id item in value) [result addObject:JSONValue(item) ?: NSNull.null];
        return result;
    }
    if ([value isKindOfClass:NSString.class] || [value isKindOfClass:NSNumber.class] || value == NSNull.null) return value;
    return value ? [value description] : NSNull.null;
}
static void Emit(NSDictionary *record) {
    NSMutableDictionary *result = [record mutableCopy];
    result[@"action"] = Action ?: @"invalid";
    NSData *data = [NSJSONSerialization dataWithJSONObject:JSONValue(result) options:NSJSONWritingPrettyPrinted error:NULL];
    puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String ?: "{}");
    fflush(stdout);
}
static int Stop(NSString *reason) { Emit(@{@"status":@"stopped", @"reason":reason}); return 1; }
static void Pump(NSTimeInterval seconds) {
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]];
}
static BOOL Focused(NSRunningApplication *app) {
    return app && NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier == app.processIdentifier;
}
static BOOL AuthenticationApp(NSRunningApplication *app) {
    NSString *identifier=app.bundleIdentifier;
    return [identifier isEqual:@"com.apple.SecurityAgent"]
        || [identifier isEqual:@"com.apple.loginwindow"]
        || [identifier isEqual:@"com.apple.LocalAuthentication.UIAgent"];
}
static BOOL Activate(NSRunningApplication *app) {
    if (!app) return NO;
    [app activateWithOptions:0];
    for (NSUInteger count=0; count<40 && !Focused(app); ++count) Pump(.1);
    return Focused(app);
}
static BOOL InputAllowed(void) { return AXIsProcessTrusted() && CGPreflightPostEventAccess(); }
static id Attribute(AXUIElementRef element, CFStringRef name) {
    CFTypeRef value = NULL;
    if (!element || AXUIElementCopyAttributeValue(element, name, &value) != kAXErrorSuccess) return nil;
    return CFBridgingRelease(value);
}
static BOOL OwnedPath(NSString *path, BOOL directory, BOOL requireExists) {
    struct stat st;
    if (lstat(path.fileSystemRepresentation, &st)) return !requireExists && errno == ENOENT;
    return !S_ISLNK(st.st_mode) && st.st_uid == getuid() && !(st.st_mode & 0022)
        && (directory ? S_ISDIR(st.st_mode) : S_ISREG(st.st_mode));
}
static BOOL RealComponents(NSString *path) {
    NSString *current = @"/";
    for (NSString *part in path.pathComponents) {
        if ([part isEqual:@"/"]) continue;
        current = [current stringByAppendingPathComponent:part];
        struct stat st;
        if (lstat(current.fileSystemRepresentation, &st)) return NO;
        if (S_ISLNK(st.st_mode) || !S_ISDIR(st.st_mode)) return NO;
    }
    return YES;
}
static BOOL LoadConfig(NSString **reason) {
    if (geteuid() != getuid() || getuid() == 0) { *reason=@"Run only as the normal current user, without elevation."; return NO; }
    NSString *home = NSHomeDirectory();
    NSString *cache = [home stringByAppendingPathComponent:@".cache/dlms-desktop-macos-preview"];
    NSString *file = [cache stringByAppendingPathComponent:@"OPENING_INPUT.json"];
    if (!RealComponents(cache) || !OwnedPath(cache, YES, YES) || !OwnedPath(file, NO, YES)) {
        *reason=@"The fixed task-owned opening configuration/cache is missing or unsafe."; return NO;
    }
    NSData *data = [NSData dataWithContentsOfFile:file];
    id config = data.length <= 16384 ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    if (![config isKindOfClass:NSDictionary.class] || [config count] != 3) {
        *reason=@"Configuration must contain exactly url, download and app."; return NO;
    }
    for (NSString *key in @[@"url", @"download", @"app"])
        if (![config[key] isKindOfClass:NSString.class] || ![config[key] length]) {
            *reason=@"Configuration values must be nonempty strings."; return NO;
        }
    NSURLComponents *url = [NSURLComponents componentsWithString:config[@"url"]];
    if (![url.scheme isEqual:@"http"] || ![url.host isEqual:@"127.0.0.1"] || !url.port
        || url.port.integerValue < 1 || url.port.integerValue > 65535 || url.user || url.password
        || url.query || url.fragment || !url.path.length || !url.URL) {
        *reason=@"Only a direct HTTP URL on explicit 127.0.0.1:port is permitted; no credentials, query or fragment."; return NO;
    }
    NSString *download = config[@"download"], *app = config[@"app"];
    NSString *folder = [download stringByDeletingLastPathComponent];
    NSString *downloads = [home stringByAppendingPathComponent:@"Downloads"];
    if (![download isAbsolutePath] || ![app isAbsolutePath]
        || ![download isEqual:download.stringByStandardizingPath] || ![app isEqual:app.stringByStandardizingPath]
        || ![[folder stringByDeletingLastPathComponent] isEqual:downloads]
        || ![folder.lastPathComponent hasPrefix:@"DLMS-Mac-preview-opening-"]
        || folder.lastPathComponent.length <= @"DLMS-Mac-preview-opening-".length
        || ![download.pathExtension.lowercaseString isEqual:@"dmg"]
        || ![app isEqual:[folder stringByAppendingPathComponent:@"DLMS Desktop.app"]]
        || !RealComponents(folder) || !OwnedPath(folder, YES, YES)
        || !OwnedPath(download, NO, NO)) {
        *reason=@"Paths must be ordinary task-owned Downloads/DLMS-Mac-preview-opening-* files; installed Applications are forbidden."; return NO;
    }
    Config = config;
    return YES;
}
static NSDictionary *Quarantine(NSString *path, NSString **reason) {
    NSURL *url = [NSURL fileURLWithPath:path];
    id value = nil; NSError *error = nil;
    if (![url getResourceValue:&value forKey:NSURLQuarantinePropertiesKey error:&error]) {
        *reason = error.localizedDescription ?: @"Could not read quarantine properties."; return nil;
    }
    return [value isKindOfClass:NSDictionary.class] ? value : nil;
}
static NSString *QuarantineBytes(NSString *path) {
    ssize_t length = getxattr(path.fileSystemRepresentation, "com.apple.quarantine", NULL, 0, 0, XATTR_NOFOLLOW);
    if (length <= 0 || length > 8192) return nil;
    NSMutableData *data = [NSMutableData dataWithLength:(NSUInteger)length];
    if (getxattr(path.fileSystemRepresentation, "com.apple.quarantine", data.mutableBytes, data.length, 0, XATTR_NOFOLLOW) != length) return nil;
    return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
}
static BOOL HasActualURL(NSDictionary *properties) {
    id value = properties[(__bridge NSString *)kLSQuarantineDataURLKey];
    NSString *url = [value isKindOfClass:NSURL.class] ? [value absoluteString] : value;
    if (url) return [url isKindOfClass:NSString.class] && [url isEqual:Config[@"url"]];
    // macOS may omit DataURL from this read API while retaining the event.
    // The runner independently verifies the actual HTTP response URL and DMG
    // hash. Accept only this downloader's own native web-download event; never
    // rewrite existing quarantine to manufacture missing provenance.
    return [properties[(__bridge NSString *)kLSQuarantineAgentBundleIdentifierKey] isEqual:AgentID]
        && [properties[(__bridge NSString *)kLSQuarantineAgentNameKey] isEqual:AgentName]
        && [properties[(__bridge NSString *)kLSQuarantineTypeKey] isEqual:(__bridge NSString *)kLSQuarantineTypeWebDownload]
        && [properties[@"LSQuarantineEventIdentifier"] isKindOfClass:NSString.class]
        && [properties[@"LSQuarantineEventIdentifier"] length] > 0;
}
static BOOL AddQuarantine(NSString *path, NSDictionary *properties, BOOL *added, NSString **reason) {
    NSString *beforeBytes = QuarantineBytes(path);
    NSDictionary *before = Quarantine(path, reason);
    if (*reason) return NO;
    if (beforeBytes || before) {
        // Existing quarantine is never rewritten: doing so could alter an OS
        // approval flag. Missing/wrong provenance is a stop, not a repair.
        if (!beforeBytes || !before || !HasActualURL(before)) {
            *reason=@"Existing quarantine lacks the exact task download provenance; it was left unchanged."; return NO;
        }
        *added=NO; return YES;
    }
    NSError *error = nil;
    if (![[NSURL fileURLWithPath:path] setResourceValue:properties forKey:NSURLQuarantinePropertiesKey error:&error]) {
        *reason=error.localizedDescription ?: @"Native quarantine addition failed."; return NO;
    }
    NSDictionary *after = Quarantine(path, reason);
    if (!QuarantineBytes(path) || !HasActualURL(after)) {
        *reason=@"Native quarantine/provenance verification failed; evidence preserved."; return NO;
    }
    *added=YES; return YES;
}

@interface DownloadDelegate : NSObject <NSURLSessionTaskDelegate>
@end
@implementation DownloadDelegate
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completionHandler {
    (void)session; (void)task; (void)response; (void)request;
    completionHandler(nil); // Never follow a loopback endpoint elsewhere.
}
@end

static int Download(void) {
    NSString *path=Config[@"download"];
    struct stat st;
    if (!lstat(path.fileSystemRepresentation,&st) || errno != ENOENT) return Stop(@"Download destination already exists or cannot be checked; never overwrite it.");
    NSURLSessionConfiguration *configuration=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.URLCache=nil; configuration.HTTPCookieStorage=nil; configuration.URLCredentialStorage=nil;
    configuration.requestCachePolicy=NSURLRequestReloadIgnoringLocalCacheData;
    configuration.timeoutIntervalForRequest=30; configuration.timeoutIntervalForResource=90;
    DownloadDelegate *delegate=[DownloadDelegate new];
    NSURLSession *session=[NSURLSession sessionWithConfiguration:configuration delegate:delegate delegateQueue:nil];
    __block BOOL done=NO, copied=NO;
    __block NSString *failure=nil;
    __block NSInteger status=0;
    NSURL *url=[NSURL URLWithString:Config[@"url"]];
    NSURLSessionDownloadTask *task=[session downloadTaskWithURL:url completionHandler:^(NSURL *temporary, NSURLResponse *response, NSError *error) {
        status=[response isKindOfClass:NSHTTPURLResponse.class] ? [(NSHTTPURLResponse *)response statusCode] : 0;
        if (error || status != 200 || ![response.URL.absoluteString isEqual:Config[@"url"]])
            failure=error.localizedDescription ?: @"Expected one direct HTTP 200 response from the configured task server.";
        else {
            NSError *copyError=nil;
            copied=[NSFileManager.defaultManager copyItemAtURL:temporary toURL:[NSURL fileURLWithPath:path] error:&copyError];
            if (!copied) failure=copyError.localizedDescription ?: @"Exclusive destination copy failed.";
        }
        @synchronized(session) { done=YES; }
    }];
    [task resume];
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:95];
    BOOL complete=NO;
    while ([deadline timeIntervalSinceNow] > 0) {
        @synchronized(session) { complete=done; }
        if (complete) break;
        Pump(.05);
    }
    if (!complete) { [task cancel]; [session invalidateAndCancel]; return Stop(@"Bounded loopback download timed out; partial evidence is preserved."); }
    [session finishTasksAndInvalidate];
    if (!copied || failure) return Stop(failure ?: @"Download failed.");
    if (!OwnedPath(path, NO, YES)) return Stop(@"Downloaded file ownership/type/mode changed; no quarantine alteration attempted.");
    NSDictionary *properties=@{
        (__bridge NSString *)kLSQuarantineAgentNameKey:AgentName,
        (__bridge NSString *)kLSQuarantineAgentBundleIdentifierKey:AgentID,
        (__bridge NSString *)kLSQuarantineTypeKey:(__bridge NSString *)kLSQuarantineTypeWebDownload,
        (__bridge NSString *)kLSQuarantineDataURLKey:url,
        (__bridge NSString *)kLSQuarantineTimeStampKey:[NSDate date],
    };
    NSString *reason=nil; BOOL added=NO;
    if (!AddQuarantine(path, properties, &added, &reason)) return Stop(reason);
    Emit(@{@"status":@"ok", @"path":path, @"http_status":@(status), @"quarantine_added":@(added),
           @"quarantine":Quarantine(path,&reason) ?: @{}, @"quarantine_xattr":QuarantineBytes(path) ?: @"",
           @"scope":@"Actual controlled loopback NSURLSession download plus native OS quarantine metadata; not a Safari end-to-end claim."});
    return 0;
}
static BOOL ValidateApp(NSString **reason) {
    NSString *path=Config[@"app"];
    if (!OwnedPath(path, YES, YES) || !RealComponents(path)) {
        *reason=@"Exact task-owned downloaded app is missing, linked or unsafe."; return NO;
    }
    NSBundle *bundle=[NSBundle bundleWithPath:path];
    if (![bundle.bundleIdentifier isEqual:PreviewID] || ![[bundle objectForInfoDictionaryKey:@"CFBundleName"] isEqual:@"DLMS Desktop"]
        || ![bundle.executablePath hasPrefix:[path stringByAppendingString:@"/Contents/MacOS/"]]) {
        *reason=@"Downloaded preview bundle identity is unexpected; no launch/input attempted."; return NO;
    }
    return YES;
}
static int MarkApp(void) {
    NSString *reason=nil;
    if (!ValidateApp(&reason)) return Stop(reason);
    NSDictionary *source=Quarantine(Config[@"download"],&reason);
    if (reason || !QuarantineBytes(Config[@"download"]) || !source || !HasActualURL(source))
        return Stop(reason ?: @"Downloaded DMG has no verified quarantine provenance; app left unchanged.");
    BOOL added=NO;
    if (!AddQuarantine(Config[@"app"],source,&added,&reason)) return Stop(reason);
    Emit(@{@"status":@"ok",@"path":Config[@"app"],@"quarantine_added":@(added),
           @"quarantine":Quarantine(Config[@"app"],&reason) ?: @{},
           @"quarantine_xattr":QuarantineBytes(Config[@"app"]) ?: @""});
    return 0;
}
static int InspectQuarantine(void) {
    NSString *reason=nil;
    NSDictionary *properties=Quarantine(Config[@"download"],&reason);
    Emit(@{@"status":@"ok",@"quarantine":properties?:@{},
           @"quarantine_xattr":QuarantineBytes(Config[@"download"])?:@"",@"read_error":reason?:@""});
    return 0;
}

@interface AXNode : NSObject
@property(strong) id element;
@property(copy) NSString *role;
@property(copy) NSString *title;
@property(copy) NSString *value;
@property(copy) NSString *desc;
@property(copy) NSString *text;
@property(copy) NSArray<AXNode *> *children;
@property BOOL secure;
@end
@implementation AXNode
@end
static NSString *Text(id value) { return [value isKindOfClass:NSString.class] ? value : @""; }
static AXNode *Snapshot(AXUIElementRef element, NSUInteger depth, NSUInteger *budget) {
    if (!element || !*budget || depth > 22) return nil;
    --*budget;
    NSNumber *hidden=Attribute(element, CFSTR("AXHidden"));
    if ([hidden isKindOfClass:NSNumber.class] && hidden.boolValue) return nil;
    AXNode *node=[AXNode new]; node.element=(__bridge id)element;
    node.role=Text(Attribute(element,kAXRoleAttribute));
    node.title=Text(Attribute(element,kAXTitleAttribute));
    node.desc=Text(Attribute(element,kAXDescriptionAttribute));
    NSString *subrole=Text(Attribute(element,kAXSubroleAttribute));
    node.secure=[node.role isEqual:@"AXSecureTextField"] || [subrole isEqual:@"AXSecureTextField"];
    node.value=!node.secure && ([node.role isEqual:@"AXStaticText"] ||
        (FinderTextValues && [node.role isEqual:@"AXTextField"]))
        ? Text(Attribute(element,kAXValueAttribute)) : @"";
    // Secure-field values are never requested, even inside a relevant dialog.
    NSMutableArray *children=[NSMutableArray array];
    NSMutableArray *parts=[NSMutableArray arrayWithArray:@[node.title,node.desc,node.value]];
    NSArray *raw=Attribute(element,kAXChildrenAttribute);
    if ([raw isKindOfClass:NSArray.class]) for (id child in raw) {
        AXNode *snapshot=Snapshot((__bridge AXUIElementRef)child,depth+1,budget);
        if (snapshot) { [children addObject:snapshot]; [parts addObject:snapshot.text]; node.secure |= snapshot.secure; }
    }
    node.children=children;
    node.text=[parts componentsJoinedByString:@"\n"];
    return node;
}
static BOOL Contains(NSString *text, NSString *needle) {
    return [text rangeOfString:needle options:NSCaseInsensitiveSearch].location != NSNotFound;
}
static BOOL TargetText(AXNode *node) {
    // A private Candidate/launcher is a different target even if its name
    // happens to share the prefix. Never approve it through this check.
    if (Contains(node.text,@"DLMS Desktop Candidate") || Contains(node.text,@"PersonalLauncher")) return NO;
    return Contains(node.text,@"DLMS Desktop");
}
static NSString *Refusal(AXNode *node) {
    if (node.secure) return @"Authentication/password field is present; no approval or elevation attempted.";
    for (NSString *word in @[@"will damage", @"contains malware", @"malware was detected", @"is damaged", @"damaged and", @"infected",
                             @"administrator", @"admin name", @"password", @"Touch ID", @"authenticate", @"authentication", @"unlock"]) {
        if (Contains(node.text,word)) return [@"Refusing malware/damage/authentication/elevation warning: " stringByAppendingString:word];
    }
    return nil;
}
static BOOL Button(AXNode *node, NSString *label) {
    return [node.role isEqual:@"AXButton"] && ([node.title isEqual:label] || [node.desc isEqual:label]);
}
static void FindButtons(AXNode *node, NSString *label, NSMutableArray<AXNode *> *results) {
    if (Button(node,label)) [results addObject:node];
    for (AXNode *child in node.children) FindButtons(child,label,results);
}
static AXNode *ApprovalScope(AXNode *node, NSString *label) {
    NSMutableArray *buttons=[NSMutableArray array]; FindButtons(node,label,buttons);
    if (!TargetText(node) || !buttons.count) return nil;
    for (AXNode *child in node.children) {
        AXNode *scope=ApprovalScope(child,label);
        if (scope) return scope;
    }
    return node;
}
static NSArray<NSRunningApplication *> *SystemUIApps(void) {
    NSMutableArray *apps=[NSMutableArray array];
    for (NSString *bundle in @[@"com.apple.coreservices.uiagent", @"com.apple.finder", @"com.apple.systempreferences"])
        [apps addObjectsFromArray:[NSRunningApplication runningApplicationsWithBundleIdentifier:bundle]];
    return apps;
}
static BOOL SecurityDialog(AXNode *node) {
    if (!TargetText(node)) return NO;
    NSString *subrole=Text(Attribute((__bridge AXUIElementRef)node.element,kAXSubroleAttribute));
    BOOL dialog=[subrole isEqual:@"AXDialog"] || [subrole isEqual:@"AXSystemDialog"] || [node.role isEqual:@"AXSheet"];
    return dialog || Contains(node.text,@"Apple could not verify") || Contains(node.text,@"cannot verify")
        || Contains(node.text,@"unidentified developer") || Contains(node.text,@"downloaded from")
        || Contains(node.text,@"not opened") || Contains(node.text,@"is damaged") || Contains(node.text,@"will damage");
}
static NSArray<AXNode *> *Windows(NSRunningApplication *app) {
    AXUIElementRef application=AXUIElementCreateApplication(app.processIdentifier);
    AXUIElementSetMessagingTimeout(application,.5);
    NSArray *raw=Attribute(application,kAXWindowsAttribute);
    NSMutableArray *windows=[NSMutableArray array];
    NSUInteger budget=3000;
    if ([raw isKindOfClass:NSArray.class]) for (id window in raw) {
        AXNode *node=Snapshot((__bridge AXUIElementRef)window,0,&budget);
        if (node) [windows addObject:node];
    }
    CFRelease(application);
    return windows;
}
static NSArray *ButtonLabels(AXNode *node) {
    NSMutableArray *labels=[NSMutableArray array];
    if ([node.role isEqual:@"AXButton"]) {
        NSString *label=node.title.length?node.title:node.desc;
        if (label.length) [labels addObject:label];
    }
    for (AXNode *child in node.children) [labels addObjectsFromArray:ButtonLabels(child)];
    return labels;
}
static NSArray *RelevantText(AXNode *node) {
    NSMutableArray *text=[NSMutableArray array];
    for (NSString *line in @[node.title,node.desc,node.value])
        if (Contains(line,@"DLMS Desktop")) [text addObject:line];
    for (AXNode *child in node.children) [text addObjectsFromArray:RelevantText(child)];
    return [[NSOrderedSet orderedSetWithArray:text] array];
}
static int InspectDialogs(void) {
    if (!InputAllowed()) return Stop(@"Accessibility/input access is not granted; no permission prompt requested.");
    NSMutableArray *records=[NSMutableArray array];
    for (NSRunningApplication *app in SystemUIApps()) for (AXNode *window in Windows(app)) {
        BOOL settings=[app.bundleIdentifier isEqual:@"com.apple.systempreferences"];
        AXNode *scope=settings ? ApprovalScope(window,@"Open Anyway") : window;
        if (!scope || (settings ? !TargetText(scope) : !SecurityDialog(scope))) continue;
        NSString *refusal=Refusal(scope);
        [records addObject:@{@"pid":@(app.processIdentifier),@"bundle_id":app.bundleIdentifier,
                             @"target_text":RelevantText(scope),@"buttons":ButtonLabels(scope),
                             @"refusal":refusal ?: NSNull.null}];
    }
    NSRunningApplication *front=NSWorkspace.sharedWorkspace.frontmostApplication;
    NSMutableArray *authentication=[NSMutableArray array];
    for (NSRunningApplication *candidate in NSWorkspace.sharedWorkspace.runningApplications) {
        NSString *identifier=candidate.bundleIdentifier?:@"";
        if ([identifier hasPrefix:@"com.apple."] &&
            (Contains(identifier,@"auth") || Contains(identifier,@"securityagent")))
            [authentication addObject:@{@"bundle_id":identifier,@"pid":@(candidate.processIdentifier),
                                       @"frontmost":@(Focused(candidate))}];
    }
    NSArray *running=[NSRunningApplication runningApplicationsWithBundleIdentifier:PreviewID];
    NSMutableArray *previews=[NSMutableArray array];
    for (NSRunningApplication *app in running)
    {
        NSMutableArray *texts=[NSMutableArray array];
        for (AXNode *window in Windows(app)) {
            // Only this new task preview is queried, never the installed
            // Candidate. Secure and editable-field values remain unread.
            [texts addObject:@{@"title":window.title?:@"",@"text":window.text?:@"",@"role":window.role?:@""}];
        }
        [previews addObject:@{@"pid":@(app.processIdentifier),@"bundle_id":PreviewID,
                             @"bundle_path":app.bundleURL.path ?: @"",@"windows":texts}];
    }
    Emit(@{@"status":@"ok", @"target_dialogs":records, @"preview_processes":previews,
           @"frontmost_bundle_id":front.bundleIdentifier?:@"",@"authentication_processes":authentication,
           @"frontmost_is_authentication":@(AuthenticationApp(front))});
    return 0;
}
static BOOL SameFileURL(id value, NSString *path) {
    NSURL *url=[value isKindOfClass:NSURL.class] ? value : ([value isKindOfClass:NSString.class] ? [NSURL URLWithString:value] : nil);
    return url.isFileURL && [url.path.stringByStandardizingPath isEqual:path];
}
static AXNode *FindIcon(AXNode *node, BOOL exactFolder, BOOL selectedAncestor) {
    AXUIElementRef element=(__bridge AXUIElementRef)node.element;
    BOOL selected=selectedAncestor || [Attribute(element,kAXSelectedAttribute) boolValue];
    if (SameFileURL(Attribute(element,kAXURLAttribute),Config[@"app"])) return node;
    BOOL exactLabel=[node.title isEqual:@"DLMS Desktop"] || [node.title isEqual:@"DLMS Desktop.app"]
        || [node.value isEqual:@"DLMS Desktop"] || [node.value isEqual:@"DLMS Desktop.app"];
    if (exactFolder && selected && exactLabel && ([node.role isEqual:@"AXTextField"] || [node.role isEqual:@"AXImage"])) return node;
    for (AXNode *child in node.children) {
        AXNode *match=FindIcon(child,exactFolder,selected);
        if (match) return match;
    }
    return nil;
}
static int FinderAction(BOOL click) {
    if (!InputAllowed()) return Stop(@"Accessibility/input access is not granted; no input or permission prompt sent.");
    NSString *reason=nil;
    if (!ValidateApp(&reason)) return Stop(reason);
    if (!QuarantineBytes(Config[@"app"])) return Stop(@"Task app has no quarantine; refuse an unquarantined opening check.");
    if ([NSRunningApplication runningApplicationsWithBundleIdentifier:PreviewID].count) return Stop(@"A preview is already running; do not disturb it.");
    if (![NSWorkspace.sharedWorkspace selectFile:Config[@"app"] inFileViewerRootedAtPath:@""])
        return Stop(@"Finder could not reveal the exact downloaded app.");
    NSRunningApplication *finder=[NSRunningApplication runningApplicationsWithBundleIdentifier:@"com.apple.finder"].firstObject;
    if (!Activate(finder)) return Stop(@"Finder did not become frontmost; no input sent.");
    AXUIElementRef application=AXUIElementCreateApplication(finder.processIdentifier);
    id focused=nil;
    AXNode *icon=nil;
    for (NSUInteger count=0; count<40 && !icon; ++count) {
        focused=Attribute(application,kAXFocusedWindowAttribute);
        if (focused) {
            NSUInteger budget=2500;
            FinderTextValues=YES;
            AXNode *window=Snapshot((__bridge AXUIElementRef)focused,0,&budget);
            FinderTextValues=NO;
            NSString *folder=[Config[@"app"] stringByDeletingLastPathComponent];
            BOOL exactFolder=SameFileURL(Attribute((__bridge AXUIElementRef)focused,kAXURLAttribute),folder)
                || SameFileURL(Attribute((__bridge AXUIElementRef)focused,kAXDocumentAttribute),folder);
            icon=FindIcon(window,exactFolder,NO);
        }
        if (!icon) Pump(.1);
    }
    if (!icon || !Focused(finder)) { CFRelease(application); return Stop(@"Exact selected app icon is unavailable in focused Finder; no input sent."); }
    id position=Attribute((__bridge AXUIElementRef)icon.element,kAXPositionAttribute);
    id size=Attribute((__bridge AXUIElementRef)icon.element,kAXSizeAttribute);
    CGPoint point; CGSize dimensions;
    if (!position || !size || CFGetTypeID((__bridge CFTypeRef)position) != AXValueGetTypeID()
        || CFGetTypeID((__bridge CFTypeRef)size) != AXValueGetTypeID()
        || !AXValueGetValue((__bridge AXValueRef)position,kAXValueCGPointType,&point)
        || !AXValueGetValue((__bridge AXValueRef)size,kAXValueCGSizeType,&dimensions)
        || dimensions.width < 4 || dimensions.height < 4 || dimensions.width > 2000 || dimensions.height > 1000) {
        CFRelease(application); return Stop(@"Exact Finder icon has no safe bounds; no input sent.");
    }
    CGPoint center=CGPointMake(point.x+dimensions.width/2,point.y+dimensions.height/2);
    if (click) for (int count=1;count<=2;++count) {
        if (!Focused(finder)) { CFRelease(application); return Stop(@"Focus changed before completing double-click; no further input sent."); }
        CGEventRef down=CGEventCreateMouseEvent(NULL,kCGEventLeftMouseDown,center,kCGMouseButtonLeft);
        CGEventRef up=CGEventCreateMouseEvent(NULL,kCGEventLeftMouseUp,center,kCGMouseButtonLeft);
        if (!down || !up) { if(down)CFRelease(down); if(up)CFRelease(up); CFRelease(application); return Stop(@"Mouse event creation failed."); }
        CGEventSetIntegerValueField(down,kCGMouseEventClickState,count);
        CGEventSetIntegerValueField(up,kCGMouseEventClickState,count);
        CGEventPost(kCGHIDEventTap,down); Pump(.03);
        CGEventPost(kCGHIDEventTap,up); Pump(.04); // Always release a posted mouse-down.
        CFRelease(down); CFRelease(up);
    }
    CFRelease(application);
    Emit(@{@"status":@"ok",@"path":Config[@"app"],@"finder_pid":@(finder.processIdentifier),
           @"input":click?@"actual Finder double-click":@"reveal and exact icon inspection only",
           @"icon_role":icon.role,@"x":@(center.x),@"y":@(center.y)});
    return 0;
}
static int OpenSettings(void) {
    if (!InputAllowed()) return Stop(@"Accessibility/input access is not granted.");
    BOOL blocked=NO;
    for (NSRunningApplication *app in SystemUIApps()) {
        if ([app.bundleIdentifier isEqual:@"com.apple.systempreferences"]) continue;
        for (AXNode *window in Windows(app)) if (SecurityDialog(window)) {
            NSString *refusal=Refusal(window);
            if (refusal) return Stop(refusal);
            blocked=YES;
        }
    }
    if (!blocked) return Stop(@"No relevant downloaded DLMS opening warning is visible; settings were not opened.");
    NSURL *url=[NSURL URLWithString:@"x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension"];
    if (![NSWorkspace.sharedWorkspace openURL:url]) return Stop(@"The supported Privacy & Security settings link was unavailable.");
    Emit(@{@"status":@"ok",@"settings_url":url.absoluteString,@"input":@"Opened Privacy & Security only; no settings changed."});
    return 0;
}
static int PressApproval(NSString *label, BOOL finalOpen) {
    if (!InputAllowed()) return Stop(@"Accessibility/input access is not granted; no input sent.");
    NSString *reason=nil;
    if (!ValidateApp(&reason) || !QuarantineBytes(Config[@"app"])) return Stop(reason ?: @"Exact app quarantine is missing.");
    NSRunningApplication *front=NSWorkspace.sharedWorkspace.frontmostApplication;
    if (AuthenticationApp(front))
        return Stop(@"Authentication/elevation is frontmost; stop without interacting.");
    NSMutableArray *matches=[NSMutableArray array];
    for (NSRunningApplication *app in SystemUIApps()) {
        BOOL settings=[app.bundleIdentifier isEqual:@"com.apple.systempreferences"];
        if (finalOpen ? settings : !settings) continue;
        for (AXNode *window in Windows(app)) {
            if (!finalOpen && !Contains(window.text,@"Privacy & Security")) continue;
            if (finalOpen && !SecurityDialog(window)) continue;
            AXNode *scope=ApprovalScope(window,label);
            if (!scope) continue;
            if (settings) {
                NSArray *sheets=Attribute((__bridge AXUIElementRef)window.element,CFSTR("AXSheets"));
                NSNumber *modal=Attribute((__bridge AXUIElementRef)window.element,CFSTR("AXModal"));
                if (sheets.count || modal.boolValue) return Stop(@"Settings has a sheet/modal dialog; no approval or authentication interaction attempted.");
            }
            NSString *refusal=Refusal(scope);
            if (refusal) return Stop(refusal);
            NSMutableArray *buttons=[NSMutableArray array]; FindButtons(scope,label,buttons);
            for (AXNode *button in buttons) [matches addObject:@{@"app":app,@"scope":scope,@"button":button}];
        }
    }
    if (matches.count != 1) return Stop(@"One exact DLMS approval control could not be verified; no click or fallback attempted.");
    NSRunningApplication *app=matches[0][@"app"]; AXNode *scope=matches[0][@"scope"], *button=matches[0][@"button"];
    if (!Activate(app)) return Stop(@"Exact system approval window did not become frontmost; no input sent.");
    AXUIElementRef element=(__bridge AXUIElementRef)button.element;
    id enabled=Attribute(element,kAXEnabledAttribute);
    CFArrayRef actions=NULL;
    BOOL press=AXUIElementCopyActionNames(element,&actions)==kAXErrorSuccess
        && CFArrayContainsValue(actions,CFRangeMake(0,CFArrayGetCount(actions)),kAXPressAction);
    if (actions) CFRelease(actions);
    if (![enabled isKindOfClass:NSNumber.class] || ![enabled boolValue] || !press || !Focused(app))
        return Stop(@"Exact approval control is not enabled/pressable/focused; no input sent.");
    if (AXUIElementPerformAction(element,kAXPressAction) != kAXErrorSuccess) return Stop(@"Native per-app approval press failed; no fallback attempted.");
    Emit(@{@"status":@"ok",@"button":label,@"pid":@(app.processIdentifier),@"bundle_id":app.bundleIdentifier,
           @"target_text":RelevantText(scope),@"scope":@"Normal visible per-app OS approval only; no global Gatekeeper change or manual quarantine removal."});
    return 0;
}
static int ConfirmOpen(void) {
    NSMutableArray *labels=[NSMutableArray array];
    for (NSRunningApplication *app in SystemUIApps()) {
        if ([app.bundleIdentifier isEqual:@"com.apple.systempreferences"]) continue;
        for (AXNode *window in Windows(app)) {
            if (!SecurityDialog(window) || Refusal(window)) continue;
            for (NSString *label in @[@"Open",@"Open Anyway"]) {
                NSMutableArray *buttons=[NSMutableArray array];FindButtons(window,label,buttons);
                for (AXNode *button in buttons) { (void)button; [labels addObject:label]; }
            }
        }
    }
    if (labels.count!=1) return Stop(@"One normal final Open/Open Anyway control could not be verified; no input sent.");
    return PressApproval(labels.firstObject,YES);
}
static int CmdQ(void) {
    if (!InputAllowed()) return Stop(@"Accessibility/input access is not granted; no input sent.");
    NSArray *apps=[NSRunningApplication runningApplicationsWithBundleIdentifier:PreviewID];
    if (apps.count != 1) return Stop(@"Expected exactly one public preview process; no input sent.");
    NSRunningApplication *app=apps.firstObject;
    NSString *bundle=app.bundleURL.path.stringByStandardizingPath;
    BOOL translocated=([bundle hasPrefix:@"/private/var/folders/"] || [bundle hasPrefix:@"/var/folders/"]) && Contains(bundle,@"/AppTranslocation/")
        && [bundle hasSuffix:@"/d/DLMS Desktop.app"];
    if (![bundle isEqual:Config[@"app"]] && !translocated) return Stop(@"Preview bundle path is neither the task download nor AppTranslocation; no input sent.");
    if (!Activate(app)) return Stop(@"Exact preview did not become frontmost; no keyboard input sent.");
    NSArray<AXNode *> *windows=Windows(app);
    AXNode *window=windows.count==1?windows.firstObject:nil;
    NSString *subrole=window?Text(Attribute((__bridge AXUIElementRef)window.element,kAXSubroleAttribute)):@"";
    NSArray *sheets=window?Attribute((__bridge AXUIElementRef)window.element,CFSTR("AXSheets")):nil;
    NSNumber *modal=window?Attribute((__bridge AXUIElementRef)window.element,CFSTR("AXModal")):nil;
    if (!window || ![window.role isEqual:@"AXWindow"] || [subrole isEqual:@"AXDialog"] || [subrole isEqual:@"AXSystemDialog"]
        || sheets.count || modal.boolValue || !Focused(app)) return Stop(@"Expected one normal preview window without sheets/modal dialogs; no keyboard input sent.");
    CGEventRef down=CGEventCreateKeyboardEvent(NULL,12,true), up=CGEventCreateKeyboardEvent(NULL,12,false);
    if (!down || !up) { if(down)CFRelease(down); if(up)CFRelease(up); return Stop(@"Keyboard event creation failed."); }
    CGEventSetFlags(down,kCGEventFlagMaskCommand); CGEventSetFlags(up,kCGEventFlagMaskCommand);
    CGEventPost(kCGHIDEventTap,down); Pump(.04);
    CGEventPost(kCGHIDEventTap,up); // Always release Q even if Cmd-Q already closed the app.
    CFRelease(down); CFRelease(up);
    Emit(@{@"status":@"ok",@"input":@"actual Cmd-Q",@"pid":@(app.processIdentifier),@"bundle_id":PreviewID,
           @"bundle_path":bundle ?: @"",@"app_translocation":@(translocated)});
    return 0;
}
int main(int argc,const char **argv) {
    @autoreleasepool {
        if (argc != 2) return Stop(@"Exactly one fixed action is required.");
        Action=[NSString stringWithUTF8String:argv[1]];
        NSSet *actions=[NSSet setWithArray:@[@"download",@"mark-app",@"inspect-quarantine",@"reveal",@"double-click",@"inspect-dialog",@"open-settings",@"dismiss-warning",@"open-anyway",@"confirm-open",@"cmd-q"]];
        if (![actions containsObject:Action]) return Stop(@"Unknown action; no operation attempted.");
        NSString *reason=nil;
        if (!LoadConfig(&reason)) return Stop(reason);
        if ([Action isEqual:@"download"]) return Download();
        if ([Action isEqual:@"mark-app"]) return MarkApp();
        if ([Action isEqual:@"inspect-quarantine"]) return InspectQuarantine();
        if ([Action isEqual:@"reveal"]) return FinderAction(NO);
        if ([Action isEqual:@"double-click"]) return FinderAction(YES);
        if ([Action isEqual:@"inspect-dialog"]) return InspectDialogs();
        if ([Action isEqual:@"open-settings"]) return OpenSettings();
        if ([Action isEqual:@"dismiss-warning"]) return PressApproval(@"Done",YES);
        if ([Action isEqual:@"open-anyway"]) return PressApproval(@"Open Anyway",NO);
        if ([Action isEqual:@"confirm-open"]) return ConfirmOpen();
        if ([Action isEqual:@"cmd-q"]) return CmdQ();
        return Stop(@"No action selected.");
    }
}
