// Project-owned fixture for the isolated emulated iOS 14 lab.
// This fixture does not assess security of any other app.
#import <UIKit/UIKit.h>

@interface LabController : UITableViewController
@property(nonatomic) NSInteger taps;
@property(nonatomic, strong) UIButton *counter;
@end

@implementation LabController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = @"HuntMob iOS Virtual";
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    UIView *header = [[UIView alloc] initWithFrame:CGRectMake(0, 0, 400, 160)];
    UILabel *label = [[UILabel alloc] initWithFrame:CGRectMake(20, 12, 340, 68)];
    label.numberOfLines = 3;
    label.font = [UIFont systemFontOfSize:15];
    label.text = @"Fixture local para validar abertura, toque e rolagem. Não representa análise de segurança de outro app.";
    [header addSubview:label];
    self.counter = [UIButton buttonWithType:UIButtonTypeSystem];
    self.counter.frame = CGRectMake(20, 88, 340, 48);
    self.counter.backgroundColor = [UIColor colorWithRed:0.9 green:0.12 blue:0.22 alpha:1];
    [self.counter setTitleColor:UIColor.whiteColor forState:UIControlStateNormal];
    [self.counter setTitle:@"Toques confirmados: 0 — aumentar" forState:UIControlStateNormal];
    [self.counter addTarget:self action:@selector(increment) forControlEvents:UIControlEventTouchUpInside];
    [header addSubview:self.counter];
    self.tableView.tableHeaderView = header;
}
- (void)increment {
    self.taps += 1;
    [self.counter setTitle:[NSString stringWithFormat:@"Toques confirmados: %ld — aumentar", (long)self.taps] forState:UIControlStateNormal];
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section {
    return 40;
}
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [tableView dequeueReusableCellWithIdentifier:@"lab"];
    if (!cell) cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:@"lab"];
    cell.textLabel.text = [NSString stringWithFormat:@"Controle de laboratório %ld", (long)indexPath.row + 1];
    return cell;
}
@end

@interface LabDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation LabDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [[UINavigationController alloc] initWithRootViewController:[[LabController alloc] initWithStyle:UITableViewStylePlain]];
    [self.window makeKeyAndVisible];
    return YES;
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass(LabDelegate.class));
    }
}
