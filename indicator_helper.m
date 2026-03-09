#import <Cocoa/Cocoa.h>

@interface IndicatorAppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSPanel *window;
@property(nonatomic, strong) NSTextField *label;
@end

@implementation IndicatorAppDelegate

- (void)shutdown {
    [self.window orderOut:nil];
    [NSApp stop:nil];
    exit(0);
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    [self setupWindow];
    [self startCommandReader];
}

- (void)setupWindow {
    NSRect screenFrame = NSScreen.mainScreen ? NSScreen.mainScreen.frame : NSMakeRect(0, 0, 1440, 900);
    CGFloat width = 132.0;
    CGFloat height = 34.0;
    CGFloat x = (NSWidth(screenFrame) - width) / 2.0;
    CGFloat y = 24.0;

    self.window = [[NSPanel alloc] initWithContentRect:NSMakeRect(x, y, width, height)
                                             styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                               backing:NSBackingStoreBuffered
                                                 defer:NO];
    self.window.opaque = NO;
    self.window.hasShadow = YES;
    self.window.backgroundColor = [NSColor colorWithWhite:0.08 alpha:0.9];
    self.window.level = NSStatusWindowLevel;
    self.window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary;
    self.window.ignoresMouseEvents = YES;
    self.window.hidesOnDeactivate = NO;

    CGFloat labelHeight = 18.0;
    CGFloat labelY = (height - labelHeight) / 2.0 - 1.0;
    self.label = [[NSTextField alloc] initWithFrame:NSMakeRect(0, labelY, width, labelHeight)];
    self.label.bezeled = NO;
    self.label.drawsBackground = NO;
    self.label.editable = NO;
    self.label.selectable = NO;
    self.label.alignment = NSTextAlignmentCenter;
    self.label.font = [NSFont monospacedSystemFontOfSize:12.0 weight:NSFontWeightSemibold];
    self.label.lineBreakMode = NSLineBreakByClipping;
    [self.window.contentView addSubview:self.label];

    [self setState:@"idle"];
    [self.window orderFrontRegardless];
}

- (void)startCommandReader {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        char buffer[256];
        while (fgets(buffer, sizeof(buffer), stdin) != NULL) {
            NSString *command = [[[NSString stringWithUTF8String:buffer]
                stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]]
                lowercaseString];

            dispatch_async(dispatch_get_main_queue(), ^{
                if ([command isEqualToString:@"exit"]) {
                    [self shutdown];
                } else {
                    [self setState:command];
                }
            });
        }

        dispatch_async(dispatch_get_main_queue(), ^{
            [self shutdown];
        });
    });
}

- (void)setState:(NSString *)state {
    if ([state isEqualToString:@"recording"]) {
        self.label.stringValue = @"● REC";
        self.label.textColor = [NSColor systemRedColor];
    } else if ([state isEqualToString:@"processing"]) {
        self.label.stringValue = @"◔ WORKING";
        self.label.textColor = [NSColor systemYellowColor];
    } else {
        self.label.stringValue = @"○ IDLE";
        self.label.textColor = [NSColor colorWithWhite:0.86 alpha:1.0];
    }

    [self.window orderFrontRegardless];
}

@end

int main(int argc, const char * argv[]) {
    (void)argc;
    (void)argv;

    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        IndicatorAppDelegate *delegate = [[IndicatorAppDelegate alloc] init];
        application.activationPolicy = NSApplicationActivationPolicyAccessory;
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
