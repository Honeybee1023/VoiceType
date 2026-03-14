#import <Cocoa/Cocoa.h>

@interface IndicatorContentView : NSView
@property(nonatomic, weak) NSWindow *targetWindow;
@end

@implementation IndicatorContentView
- (BOOL)acceptsFirstMouse:(NSEvent *)event {
    (void)event;
    return YES;
}

- (void)mouseDown:(NSEvent *)event {
    NSView *hit = [self hitTest:[self convertPoint:event.locationInWindow fromView:nil]];
    if ([hit isKindOfClass:[NSButton class]]) {
        [super mouseDown:event];
        return;
    }
    if (self.targetWindow != nil) {
        [self.targetWindow performWindowDragWithEvent:event];
        return;
    }
    [super mouseDown:event];
}
@end

@interface DragHandleView : NSView
@property(nonatomic, weak) NSWindow *targetWindow;
@end

@implementation DragHandleView
- (BOOL)acceptsFirstMouse:(NSEvent *)event {
    (void)event;
    return YES;
}

- (void)mouseDown:(NSEvent *)event {
    if (self.targetWindow != nil) {
        [self.targetWindow performWindowDragWithEvent:event];
        return;
    }
    [super mouseDown:event];
}

- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];
    [[NSColor colorWithWhite:0.7 alpha:0.8] setFill];
    CGFloat dot = 2.2;
    CGFloat gap = 3.6;
    CGFloat startX = (NSWidth(self.bounds) - (3 * dot + 2 * gap)) / 2.0;
    CGFloat startY = (NSHeight(self.bounds) - (2 * dot + gap)) / 2.0;
    for (NSInteger row = 0; row < 2; row++) {
        for (NSInteger col = 0; col < 3; col++) {
            CGFloat x = startX + col * (dot + gap);
            CGFloat y = startY + row * (dot + gap);
            NSRect dotRect = NSMakeRect(x, y, dot, dot);
            NSBezierPath *path = [NSBezierPath bezierPathWithOvalInRect:dotRect];
            [path fill];
        }
    }
}
@end

@interface NonInteractiveTextField : NSTextField
@end

@implementation NonInteractiveTextField
- (NSView *)hitTest:(NSPoint)point {
    (void)point;
    return nil;
}
@end

@interface DraggableButton : NSButton
@property(nonatomic, weak) NSWindow *targetWindow;
@property(nonatomic) NSPoint dragStart;
@property(nonatomic) BOOL didDrag;
@end

@implementation DraggableButton
- (void)mouseDown:(NSEvent *)event {
    self.dragStart = event.locationInWindow;
    self.didDrag = NO;
    [super mouseDown:event];
}

- (void)mouseDragged:(NSEvent *)event {
    CGFloat dx = fabs(event.locationInWindow.x - self.dragStart.x);
    CGFloat dy = fabs(event.locationInWindow.y - self.dragStart.y);
    if (!self.didDrag && (dx > 3.0 || dy > 3.0)) {
        self.didDrag = YES;
    }
    if (self.didDrag && self.targetWindow != nil) {
        [self.targetWindow performWindowDragWithEvent:event];
    } else {
        [super mouseDragged:event];
    }
}

- (void)mouseUp:(NSEvent *)event {
    if (self.didDrag) {
        self.didDrag = NO;
        return;
    }
    [super mouseUp:event];
}
@end

@interface IndicatorAppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSPanel *window;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSTextField *languageLabel;
@property(nonatomic, strong) DraggableButton *languageButton;
@property(nonatomic, strong) DraggableButton *toggleButton;
@property(nonatomic, strong) DragHandleView *dragHandle;
@property(nonatomic, strong) NSMenu *languageMenu;
@property(nonatomic, copy) NSString *currentState;
@property(nonatomic, copy) NSString *currentLanguage;
@end

@implementation IndicatorAppDelegate

- (void)shutdown {
    [self.window orderOut:nil];
    [NSApp stop:nil];
    exit(0);
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    self.currentState = @"idle";
    self.currentLanguage = @"en";
    [self setupWindow];
    [self startCommandReader];
}

- (void)setupWindow {
    NSRect screenFrame = NSScreen.mainScreen ? NSScreen.mainScreen.frame : NSMakeRect(0, 0, 1440, 900);
    CGFloat width = 168.0;
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
    self.window.ignoresMouseEvents = NO;
    self.window.hidesOnDeactivate = NO;
    self.window.movableByWindowBackground = YES;

    IndicatorContentView *contentView = [[IndicatorContentView alloc] initWithFrame:NSMakeRect(0.0, 0.0, width, height)];
    contentView.targetWindow = self.window;
    self.window.contentView = contentView;

    CGFloat handleWidth = 22.0;
    CGFloat statusWidth = 96.0;
    CGFloat labelHeight = 18.0;
    CGFloat labelY = (height - labelHeight) / 2.0 - 1.0;

    self.dragHandle = [[DragHandleView alloc] initWithFrame:NSMakeRect(6.0, 4.0, handleWidth, height - 8.0)];
    self.dragHandle.targetWindow = self.window;
    [contentView addSubview:self.dragHandle];

    self.statusLabel = [[NonInteractiveTextField alloc] initWithFrame:NSMakeRect(10.0 + handleWidth, labelY, statusWidth, labelHeight)];
    self.statusLabel.bezeled = NO;
    self.statusLabel.drawsBackground = NO;
    self.statusLabel.editable = NO;
    self.statusLabel.selectable = NO;
    self.statusLabel.alignment = NSTextAlignmentLeft;
    self.statusLabel.font = [NSFont monospacedSystemFontOfSize:12.0 weight:NSFontWeightSemibold];
    self.statusLabel.lineBreakMode = NSLineBreakByClipping;
    [contentView addSubview:self.statusLabel];

    self.toggleButton = [[DraggableButton alloc] initWithFrame:NSMakeRect(10.0 + handleWidth, 4.0, 122.0 - handleWidth, 26.0)];
    self.toggleButton.bordered = NO;
    self.toggleButton.title = @"";
    self.toggleButton.target = self;
    self.toggleButton.action = @selector(toggleRecording:);
    self.toggleButton.toolTip = @"Click to start/stop recording";
    self.toggleButton.targetWindow = self.window;
    [contentView addSubview:self.toggleButton];

    self.languageLabel = [[NonInteractiveTextField alloc] initWithFrame:NSMakeRect(106.0, labelY, 32.0, labelHeight)];
    self.languageLabel.bezeled = NO;
    self.languageLabel.drawsBackground = NO;
    self.languageLabel.editable = NO;
    self.languageLabel.selectable = NO;
    self.languageLabel.alignment = NSTextAlignmentRight;
    self.languageLabel.font = [NSFont monospacedSystemFontOfSize:11.0 weight:NSFontWeightMedium];
    self.languageLabel.textColor = [NSColor colorWithWhite:0.78 alpha:1.0];
    [contentView addSubview:self.languageLabel];

    self.languageButton = [[DraggableButton alloc] initWithFrame:NSMakeRect(142.0, 5.0, 20.0, 24.0)];
    self.languageButton.bordered = NO;
    self.languageButton.title = @"▴";
    self.languageButton.font = [NSFont systemFontOfSize:11.0 weight:NSFontWeightBold];
    self.languageButton.contentTintColor = [NSColor colorWithWhite:0.88 alpha:1.0];
    self.languageButton.target = self;
    self.languageButton.action = @selector(showLanguageMenu:);
    self.languageButton.targetWindow = self.window;
    [contentView addSubview:self.languageButton];

    self.languageMenu = [[NSMenu alloc] initWithTitle:@"Language"];
    [self.languageMenu addItemWithTitle:@"English" action:@selector(selectLanguage:) keyEquivalent:@""];
    [self.languageMenu addItemWithTitle:@"Chinese Simplified" action:@selector(selectLanguage:) keyEquivalent:@""];
    [self.languageMenu addItemWithTitle:@"Chinese Traditional" action:@selector(selectLanguage:) keyEquivalent:@""];
    for (NSMenuItem *item in self.languageMenu.itemArray) {
        item.target = self;
    }

    [self refreshDisplay];
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
                    return;
                }
                if ([command hasPrefix:@"lang:"]) {
                    NSString *language = [command substringFromIndex:5];
                    [self setLanguage:language emitSelection:NO];
                    return;
                }
                [self setState:command];
            });
        }

        dispatch_async(dispatch_get_main_queue(), ^{
            [self shutdown];
        });
    });
}

- (void)toggleRecording:(id)sender {
    (void)sender;
    fprintf(stdout, "toggle\n");
    fflush(stdout);
}

- (void)showLanguageMenu:(id)sender {
    (void)sender;
    NSMenuItem *selectedItem = [self menuItemForLanguage:self.currentLanguage];
    [self.languageMenu popUpMenuPositioningItem:selectedItem
                                     atLocation:NSMakePoint(104.0, NSHeight(self.window.contentView.bounds) + 4.0)
                                         inView:self.window.contentView];
}

- (void)selectLanguage:(NSMenuItem *)item {
    NSString *title = item.title.lowercaseString;
    NSString *language = @"en";
    if ([title hasPrefix:@"chinese simplified"]) {
        language = @"zh-hans";
    } else if ([title hasPrefix:@"chinese traditional"]) {
        language = @"zh-hant";
    }
    [self setLanguage:language emitSelection:YES];
}

- (NSMenuItem *)menuItemForLanguage:(NSString *)language {
    NSString *title = @"English";
    if ([language isEqualToString:@"zh-hans"]) {
        title = @"Chinese Simplified";
    } else if ([language isEqualToString:@"zh-hant"]) {
        title = @"Chinese Traditional";
    }
    return [self.languageMenu itemWithTitle:title];
}

- (void)setState:(NSString *)state {
    self.currentState = state.length > 0 ? state : @"idle";
    [self refreshDisplay];
}

- (void)setLanguage:(NSString *)language emitSelection:(BOOL)emitSelection {
    NSString *normalized = @"en";
    if ([language isEqualToString:@"zh-hans"]) {
        normalized = @"zh-hans";
    } else if ([language isEqualToString:@"zh-hant"]) {
        normalized = @"zh-hant";
    }
    self.currentLanguage = normalized;
    [self refreshDisplay];
    if (emitSelection) {
        fprintf(stdout, "mode:%s\n", normalized.UTF8String);
        fflush(stdout);
    }
}

- (void)refreshDisplay {
    if ([self.currentState isEqualToString:@"recording"]) {
        self.statusLabel.stringValue = @"● REC";
        self.statusLabel.textColor = [NSColor systemRedColor];
    } else if ([self.currentState isEqualToString:@"processing"]) {
        self.statusLabel.stringValue = @"◔ WORKING";
        self.statusLabel.textColor = [NSColor systemYellowColor];
    } else {
        self.statusLabel.stringValue = @"○ IDLE";
        self.statusLabel.textColor = [NSColor colorWithWhite:0.86 alpha:1.0];
    }

    if ([self.currentLanguage isEqualToString:@"zh-hans"]) {
        self.languageLabel.stringValue = @"SIM";
    } else if ([self.currentLanguage isEqualToString:@"zh-hant"]) {
        self.languageLabel.stringValue = @"TRD";
    } else {
        self.languageLabel.stringValue = @"EN";
    }
    [self.languageMenu.itemArray enumerateObjectsUsingBlock:^(NSMenuItem *item, NSUInteger idx, BOOL *stop) {
        (void)idx;
        BOOL selected = (item == [self menuItemForLanguage:self.currentLanguage]);
        item.state = selected ? NSControlStateValueOn : NSControlStateValueOff;
        (void)stop;
    }];

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
