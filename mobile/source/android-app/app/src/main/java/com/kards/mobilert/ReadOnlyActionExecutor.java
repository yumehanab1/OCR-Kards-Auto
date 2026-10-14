package com.kards.mobilert;

/**
 * Safe executor used while recognition and post-action verification are being
 * validated.  It never calls dispatchGesture and therefore cannot touch KARDS.
 */
public final class ReadOnlyActionExecutor implements ActionExecutor {
    @Override
    public ActionResult execute(ActionRequest request, BoardObservation observation) {
        if (request == null) {
            return ActionResult.rejected("动作请求为空");
        }
        if (!ActionVerifier.mayAttempt(observation)) {
            return ActionResult.rejected("板面未取得新鲜且已授权的我方回合观察；保持只读");
        }
        return ActionResult.rejected("APK 动作执行器尚未启用；本版本保持只读");
    }
}
