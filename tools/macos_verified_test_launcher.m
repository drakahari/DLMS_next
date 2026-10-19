// Task-only explicit-root launcher. Configuration and inventory are signed resources.
#import <AppKit/AppKit.h>
#import <CommonCrypto/CommonDigest.h>
#include <sys/stat.h>
#include <unistd.h>

static BOOL Ordinary(NSString *path, BOOL directory) {
    struct stat s;
    if (lstat(path.fileSystemRepresentation, &s) ||
        (directory ? !S_ISDIR(s.st_mode) : !S_ISREG(s.st_mode))) return NO;
    for (NSString *p = path.stringByDeletingLastPathComponent; p.length > 1;
         p = p.stringByDeletingLastPathComponent)
        if (lstat(p.fileSystemRepresentation, &s) || !S_ISDIR(s.st_mode)) return NO;
    return YES;
}
static BOOL Verify(NSString *path) {
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:@"/usr/bin/codesign"];
    task.arguments = @[@"--verify", @"--deep", @"--strict", path];
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) return NO;
    [task waitUntilExit];
    return task.terminationReason == NSTaskTerminationReasonExit && task.terminationStatus == 0;
}
static NSDictionary *Inventory(NSString *root) {
    NSMutableDictionary *result = [NSMutableDictionary new];
    NSArray *paths = [@[@""] arrayByAddingObjectsFromArray:
        [[NSFileManager defaultManager] subpathsAtPath:root] ?: @[]];
    for (NSString *rel in paths) {
        NSString *path = rel.length ? [root stringByAppendingPathComponent:rel] : root;
        struct stat s;
        if (lstat(path.fileSystemRepresentation, &s)) return nil;
        NSMutableDictionary *entry = [@{@"mode": @(s.st_mode & 0777)} mutableCopy];
        if (S_ISLNK(s.st_mode)) {
            NSString *target = [[NSFileManager defaultManager] destinationOfSymbolicLinkAtPath:path error:nil];
            if (!target) return nil;
            entry[@"symlink"] = target;
        } else if (S_ISREG(s.st_mode)) {
            NSInputStream *stream = [NSInputStream inputStreamWithFileAtPath:path];
            [stream open]; CC_SHA256_CTX context; CC_SHA256_Init(&context);
            uint8_t buffer[65536]; NSInteger count;
            while ((count = [stream read:buffer maxLength:sizeof(buffer)]) > 0)
                CC_SHA256_Update(&context, buffer, (CC_LONG)count);
            [stream close]; if (count < 0) return nil;
            unsigned char hash[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_Final(hash, &context);
            NSMutableString *hex = [NSMutableString new];
            for (int i=0; i<CC_SHA256_DIGEST_LENGTH; i++) [hex appendFormat:@"%02x", hash[i]];
            entry[@"sha256"] = hex;
        } else if (S_ISDIR(s.st_mode)) entry[@"directory"] = @YES;
        else return nil;
        result[rel] = entry;
    }
    return result;
}
static NSDictionary *CheckedConfiguration(void) {
    NSBundle *selfBundle = NSBundle.mainBundle;
    // A dirty wrapper cannot launch even when double-clicked directly in Finder.
    if (!Ordinary(selfBundle.bundlePath, YES) || !Verify(selfBundle.bundlePath)) return nil;
    NSData *bytes = [NSData dataWithContentsOfFile:[selfBundle pathForResource:@"Task" ofType:@"json"]];
    NSDictionary *c = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:nil] : nil;
    if (![c isKindOfClass:NSDictionary.class] || geteuid() != getuid()) return nil;
    NSString *app = c[@"app"], *root = c[@"data_root"], *profile = c[@"profile"];
    NSString *markerPath = [root stringByAppendingPathComponent:@".dlms-macos-preview.json"];
    struct stat s;
    if (![app isKindOfClass:NSString.class] || ![root isKindOfClass:NSString.class] ||
        ![profile isKindOfClass:NSString.class] || !profile.length ||
        !Ordinary(app, YES) || !Ordinary(root, YES) || !Ordinary(markerPath, NO) ||
        lstat(root.fileSystemRepresentation, &s) || s.st_uid != getuid() || (s.st_mode & 077) ||
        ![[NSBundle bundleWithPath:app].bundleIdentifier isEqual:c[@"bundle_identifier"]]) return nil;
    NSDictionary *marker = [NSJSONSerialization JSONObjectWithData:
        [NSData dataWithContentsOfFile:markerPath] options:0 error:nil];
    if (![marker isEqual:@{@"kind":@"dlms-desktop-macos-preview", @"version":@1}] ||
        !Verify(app) || ![Inventory(app) isEqual:c[@"payload_inventory"]]) return nil;
    return c;
}
@interface TaskLauncher : NSObject <NSApplicationDelegate>
@end
@implementation TaskLauncher
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSDictionary *c = CheckedConfiguration();
    if (!c) {
        NSAlert *alert = [NSAlert new];
        alert.messageText = @"DLMS test candidate verification failed";
        alert.informativeText = @"Nothing was launched. Preserve this wrapper and its metadata for inspection. No alternate profile or security override will be used.";
        [alert runModal]; [NSApp terminate:nil]; return;
    }
    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    configuration.arguments = @[@"--data-root", c[@"data_root"], @"--profile", c[@"profile"]];
    configuration.activates = YES;
    configuration.createsNewApplicationInstance = YES;
    [[NSWorkspace sharedWorkspace] openApplicationAtURL:[NSURL fileURLWithPath:c[@"app"]]
        configuration:configuration completionHandler:^(NSRunningApplication *app, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!app || error) {
                NSAlert *alert = [NSAlert new]; alert.messageText = @"macOS did not open the test candidate";
                alert.informativeText = error.localizedDescription ?: @"Stop and inspect; keep macOS protections enabled.";
                [alert runModal];
            }
            [NSApp terminate:nil];
        });
    }];
}
@end
int main(int argc, const char **argv) {
    @autoreleasepool {
        // Bounded regression entry: never opens an app or displays an alert.
        if (argc == 2 && !strcmp(argv[1], "--verify-only")) return CheckedConfiguration() ? 0 : 1;
        if (argc != 1) return 2;
        NSApplication *app = NSApplication.sharedApplication;
        TaskLauncher *delegate = [TaskLauncher new]; app.delegate = delegate;
        [app run];
    }
    return 0;
}
