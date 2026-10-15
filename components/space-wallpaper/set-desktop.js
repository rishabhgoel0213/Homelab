// Use macOS's built-in Objective-C bridge; no Python/libffi callbacks are needed.
ObjC.import('AppKit');

function run(argv) {
    const screens = $.NSScreen.screens;
    const count = Number(screens.count);
    if (!count) throw new Error('No desktop screens in this login session');
    const workspace = $.NSWorkspace.sharedWorkspace;
    const options = $.NSMutableDictionary.alloc.init;
    options.setObjectForKey($(Number($.NSImageScaleProportionallyUpOrDown)), $.NSWorkspaceDesktopImageScalingKey);
    options.setObjectForKey($(false), $.NSWorkspaceDesktopImageAllowClippingKey);
    options.setObjectForKey($.NSColor.blackColor, $.NSWorkspaceDesktopImageFillColorKey);

    // Read-only live validation of the bridge and screen access.
    if (argv.length === 1 && argv[0] === '--check') {
        return JSON.stringify({screens: count, currentURL: ObjC.unwrap(
            workspace.desktopImageURLForScreen(screens.objectAtIndex(0)).absoluteString)});
    }
    if (argv.length !== 1) throw new Error('Expected one local wallpaper path');
    const url = $.NSURL.fileURLWithPath($(argv[0]));
    if (!$.NSFileManager.defaultManager.fileExistsAtPath($(argv[0]))) {
        throw new Error('Wallpaper file does not exist');
    }
    const previous = [];
    for (let i = 0; i < count; i++) {
        const screen = screens.objectAtIndex(i);
        previous.push({screen: screen, url: workspace.desktopImageURLForScreen(screen),
            options: workspace.desktopImageOptionsForScreen(screen)});
    }
    let updated = 0;
    try {
        for (let i = 0; i < count; i++) {
            const error = Ref();
            const ok = workspace.setDesktopImageURLForScreenOptionsError(url, previous[i].screen, options, error);
            if (!ok) throw new Error('macOS rejected the wallpaper: ' + ObjC.unwrap(error[0].localizedDescription));
            updated++;
        }
    } catch (error) {
        for (let i = 0; i < updated; i++) {
            if (previous[i].url) {
                workspace.setDesktopImageURLForScreenOptionsError(previous[i].url,
                    previous[i].screen, previous[i].options, Ref());
            }
        }
        throw error;
    }
    return JSON.stringify({screens: count, image: argv[0]});
}
