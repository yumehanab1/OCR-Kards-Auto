package com.kards.mobilert;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.Random;
import java.util.function.Predicate;

/**
 * Pure combat decision rules shared by the future Android turn loop.
 *
 * <p>This class deliberately knows nothing about Android, screenshots, or
 * input.  It accepts immutable observations and returns an immutable plan.
 * Unknown board facts produce {@link Kind#PENDING}; callers must not turn a
 * pending plan into input.</p>
 */
public final class CombatPolicy {
    private CombatPolicy() {
    }

    public enum Kind {
        ATTACK_HQ,
        ATTACK_UNIT,
        MOVE_FRONT,
        BOMBER_CHOICE,
        PENDING,
        NONE
    }

    public enum TargetCategory {
        HQ,
        ENEMY_FRONT,
        GUARD,
        FRONTLINE,
        BOMBER_CHOICE,
        NONE
    }

    public enum UnitType {
        INFANTRY,
        TANK,
        ARTILLERY,
        FIGHTER,
        BOMBER,
        UNKNOWN
    }

    public enum Row {
        SUPPORT,
        FRONT,
        ENEMY_SUPPORT,
        ENEMY_FRONT,
        UNKNOWN
    }

    public enum Owner {
        OUR,
        ENEMY,
        EMPTY,
        UNKNOWN
    }

    /** A card position and its explicitly observed protection state. */
    public static final class Card {
        private final String id;
        private final int cx;
        private final int cy;
        private final Row row;
        private final boolean protectedTarget;
        private final Protection protection;

        public Card(String id, int cx, int cy, Row row) {
            this(id, cx, cy, row, false, Protection.CLEAR);
        }

        public Card(String id, int cx, int cy, Row row, boolean protectedTarget,
                    Protection protection) {
            this.id = id == null ? "" : id;
            this.cx = cx;
            this.cy = cy;
            this.row = row == null ? Row.UNKNOWN : row;
            this.protectedTarget = protectedTarget;
            this.protection = protection == null ? Protection.CLEAR : protection;
        }

        public String id() {
            return id;
        }

        public int cx() {
            return cx;
        }

        public int cy() {
            return cy;
        }

        public Row row() {
            return row;
        }

        public boolean protectedTarget() {
            return protectedTarget;
        }

        public Protection protection() {
            return protection;
        }

        public Card withProtection(boolean isProtected, Protection state) {
            return new Card(id, cx, cy, row, isProtected, state);
        }
    }

    public enum Protection {
        CLEAR,
        PROTECTED,
        UNKNOWN
    }

    /** An immutable observed combat unit. */
    public static final class Unit {
        private final String id;
        private final UnitType type;
        private final Row row;
        private final Card card;

        public Unit(String id, UnitType type, Row row, Card card) {
            this.id = id == null ? "" : id;
            this.type = type == null ? UnitType.UNKNOWN : type;
            this.row = row == null ? Row.UNKNOWN : row;
            this.card = card;
        }

        public String id() {
            return id;
        }

        public UnitType type() {
            return type;
        }

        public Row row() {
            return row;
        }

        public Card card() {
            return card;
        }
    }

    /** HQ protection facts. A null hqGuards means use the legacy guards list. */
    public static final class GuardInfo {
        private final GuardStatus status;
        private final List<Card> guards;
        private final List<Card> hqGuards;

        public GuardInfo(GuardStatus status, List<Card> guards) {
            this(status, guards, null);
        }

        public GuardInfo(GuardStatus status, List<Card> guards, List<Card> hqGuards) {
            this.status = status == null ? GuardStatus.UNKNOWN : status;
            this.guards = immutable(guards);
            this.hqGuards = hqGuards == null ? null : immutable(hqGuards);
        }

        public GuardStatus status() {
            return status;
        }

        public List<Card> guards() {
            return guards;
        }

        public List<Card> hqGuards() {
            return hqGuards;
        }

        private List<Card> effectiveHqGuards() {
            return hqGuards == null ? guards : hqGuards;
        }
    }

    public enum GuardStatus {
        CLEAR,
        GUARDED,
        UNKNOWN
    }

    /** Immutable board observation consumed by choose/revalidate. */
    public static final class Observation {
        private final Owner owner;
        private final List<Unit> units;
        private final Card hq;
        private final Integer hqHp;
        private final List<Card> enemyFront;
        private final GuardInfo guard;

        public Observation(Owner owner, List<Unit> units, Card hq, Integer hqHp,
                           List<Card> enemyFront, GuardInfo guard) {
            this.owner = owner == null ? Owner.UNKNOWN : owner;
            this.units = immutable(units);
            this.hq = hq;
            this.hqHp = hqHp;
            this.enemyFront = immutable(enemyFront);
            this.guard = guard == null ? new GuardInfo(GuardStatus.UNKNOWN, List.of()) : guard;
        }

        public Owner owner() {
            return owner;
        }

        public List<Unit> units() {
            return units;
        }

        public Card hq() {
            return hq;
        }

        public Integer hqHp() {
            return hqHp;
        }

        public List<Card> enemyFront() {
            return enemyFront;
        }

        public GuardInfo guard() {
            return guard;
        }

        public Observation withUnits(List<Unit> replacement) {
            return new Observation(owner, replacement, hq, hqHp, enemyFront, guard);
        }
    }

    /** Immutable output. A pending/none plan never authorizes an action. */
    public static final class Plan {
        private final Kind kind;
        private final Unit unit;
        private final Card target;
        private final UnitType actorType;
        private final TargetCategory targetCategory;
        private final Owner frontOwner;
        private final Double bomberRoll;
        private final String reason;
        private final BomberTargets bomberTargets;

        private Plan(Kind kind, Unit unit, Card target, TargetCategory targetCategory,
                     Owner frontOwner, Double bomberRoll, String reason) {
            this(kind, unit, target, null, targetCategory, frontOwner, bomberRoll, reason);
        }

        private Plan(Kind kind, Unit unit, Card target, BomberTargets bomberTargets,
                     TargetCategory targetCategory, Owner frontOwner, Double bomberRoll,
                     String reason) {
            this.kind = kind;
            this.unit = unit;
            this.target = target;
            this.actorType = unit == null ? UnitType.UNKNOWN : unit.type();
            this.targetCategory = targetCategory == null ? TargetCategory.NONE : targetCategory;
            this.frontOwner = frontOwner == null ? Owner.UNKNOWN : frontOwner;
            this.bomberRoll = bomberRoll;
            this.reason = reason == null ? "" : reason;
            this.bomberTargets = bomberTargets;
        }

        public Kind kind() {
            return kind;
        }

        public Unit unit() {
            return unit;
        }

        public Card target() {
            return target;
        }

        public UnitType actorType() {
            return actorType;
        }

        public TargetCategory targetCategory() {
            return targetCategory;
        }

        public Owner frontOwner() {
            return frontOwner;
        }

        public Double bomberRoll() {
            return bomberRoll;
        }

        public String reason() {
            return reason;
        }

        public boolean isAction() {
            return kind == Kind.ATTACK_HQ || kind == Kind.ATTACK_UNIT || kind == Kind.MOVE_FRONT;
        }
    }

    @FunctionalInterface
    public interface ActorMatcher {
        List<Unit> match(List<Unit> current, Unit previous);
    }

    /** Chooses with a process-local random source only when a bomber is present. */
    public static Plan choose(Observation observation) {
        return choose(observation, (Random) null, null, null);
    }

    /** Uses the supplied random source only if a bomber target must be chosen. */
    public static Plan choose(Observation observation, Random random) {
        return choose(observation, random, null, null);
    }

    public static Plan choose(Observation observation, Double bomberRoll) {
        return choose(observation, null, bomberRoll, null);
    }

    public static Plan choose(Observation observation, Double bomberRoll,
                              Predicate<Plan> allow) {
        return choose(observation, null, bomberRoll, allow);
    }

    /** Port of mobile_combat_policy.choose. */
    public static Plan choose(Observation observation, Random random, Double bomberRoll,
                              Predicate<Plan> allow) {
        if (observation == null || observation.owner() == Owner.UNKNOWN) {
            return pending(Owner.UNKNOWN, "前线归属待确认", bomberRoll);
        }
        List<String> pendingReasons = new ArrayList<>();
        List<Plan> actions = new ArrayList<>();
        List<Plan> moves = new ArrayList<>();
        for (Unit actor : observation.units()) {
            Plan option = actorOptions(observation, actor);
            if (option.kind() == Kind.PENDING) {
                pendingReasons.add(option.reason());
            } else if (option.kind() == Kind.MOVE_FRONT) {
                moves.add(option);
            } else {
                actions.add(option);
            }
        }
        Double roll = bomberRoll;
        boolean denied = false;
        List<Plan> candidates = new ArrayList<>(actions);
        candidates.addAll(moves);
        for (Plan candidate : candidates) {
            Plan plan = candidate;
            if (plan.kind() == Kind.BOMBER_CHOICE) {
                if (roll == null) {
                    if (random == null) {
                        roll = Math.random();
                    } else {
                        roll = random.nextDouble();
                    }
                }
                validateRoll(roll);
                TargetCategory category = roll < 0.5 ? TargetCategory.HQ : TargetCategory.ENEMY_FRONT;
                // The temporary choice stores HQ and front cards outside the public target.
                BomberTargets pair = plan.bomberTargets;
                if (pair == null) {
                    return pending(observation.owner(), "轰炸机目标集合待确认", roll);
                }
                Card target;
                target = category == TargetCategory.HQ ? pair.hq : pair.front;
                plan = new Plan(category == TargetCategory.HQ ? Kind.ATTACK_HQ : Kind.ATTACK_UNIT,
                        plan.unit(), target, category, plan.frontOwner(), roll,
                        category == TargetCategory.HQ ? "轰炸机掷骰命中总部" : "轰炸机掷骰命中敌前线");
            }
            if (allow == null || allow.test(plan)) {
                return plan;
            }
            denied = true;
        }
        if (!pendingReasons.isEmpty()) {
            return pending(observation.owner(), pendingReasons.get(0), roll);
        }
        return new Plan(Kind.NONE, null, null, TargetCategory.NONE, observation.owner(), roll,
                denied ? "当前局面行动失败重试已到上限" : "没有合法行动");
    }

    /** Revalidate only the original actor/target category; never rerolls a bomber. */
    public static Plan revalidate(Observation observation, Plan original,
                                  ActorMatcher actorMatcher, int targetTolerance) {
        if (original == null || original.kind() == Kind.PENDING || original.kind() == Kind.NONE) {
            return original;
        }
        if (observation == null || observation.owner() != original.frontOwner()) {
            return pending(observation == null ? Owner.UNKNOWN : observation.owner(),
                    "输入前前线归属变化，原决策作废", original.bomberRoll());
        }
        if (actorMatcher == null || original.unit() == null) {
            return pending(observation.owner(), "原攻击者不再是同类型的唯一橙色候选", original.bomberRoll());
        }
        List<Unit> actors = actorMatcher.match(observation.units(), original.unit());
        if (actors == null || actors.size() != 1 || actors.get(0).type() != original.actorType()) {
            return pending(observation.owner(), "原攻击者不再是同类型的唯一橙色候选", original.bomberRoll());
        }
        Observation narrowed = observation.withUnits(actors);
        Plan option = actorOptions(narrowed, actors.get(0));
        if (option.kind() == Kind.BOMBER_CHOICE && original.bomberRoll() == null) {
            return pending(observation.owner(), "轰炸机目标集合变化，原决策作废", original.bomberRoll());
        }
        Plan current = choose(narrowed, null, original.bomberRoll(), null);
        if (current.kind() != original.kind() || current.targetCategory() != original.targetCategory()) {
            return pending(observation.owner(), "目标类别或守护状态变化，原决策作废", original.bomberRoll());
        }
        Card oldTarget = original.target();
        Card newTarget = current.target();
        if (oldTarget != null && (newTarget == null
                || Math.abs(newTarget.cx() - oldTarget.cx()) > targetTolerance
                || Math.abs(newTarget.cy() - oldTarget.cy()) > targetTolerance)) {
            return pending(observation.owner(), "原目标位置变化，原决策作废", original.bomberRoll());
        }
        return current;
    }

    public static Plan revalidate(Observation observation, Plan original,
                                  ActorMatcher actorMatcher) {
        return revalidate(observation, original, actorMatcher, 26);
    }

    private static Plan actorOptions(Observation observation, Unit actor) {
        Owner owner = observation.owner();
        UnitType type = actor == null ? UnitType.UNKNOWN : actor.type();
        Row row = actor == null ? Row.UNKNOWN : actor.row();
        if (type == UnitType.UNKNOWN || actor == null || actor.card() == null) {
            return pending(owner, "单位类型待确认，不推断远程能力或移动权限", null);
        }
        if (row != Row.SUPPORT && row != Row.FRONT) {
            return pending(owner, "攻击者所在行待确认", null);
        }
        boolean ground = type == UnitType.INFANTRY || type == UnitType.TANK;
        Card hq = observation.hq();
        if (ground && row == Row.SUPPORT) {
            if (owner == Owner.ENEMY) {
                if (observation.enemyFront().isEmpty()) {
                    return pending(owner, "敌占前线但目标卡未确认，等待新帧", null);
                }
                List<Card> legal = new ArrayList<>();
                for (Card card : observation.enemyFront()) {
                    if (!card.protectedTarget() && card.protection() != Protection.UNKNOWN) {
                        legal.add(card);
                    }
                }
                if (legal.isEmpty()) {
                    return pending(owner, "敌方前线均被守护或守护状态待确认", null);
                }
                return plan(Kind.ATTACK_UNIT, actor, nearest(legal, actor),
                        TargetCategory.ENEMY_FRONT, owner, "地面支援单位先清除敌方前线", null);
            }
            if (owner == Owner.OUR || owner == Owner.EMPTY) {
                return plan(Kind.MOVE_FRONT, actor, null, TargetCategory.FRONTLINE, owner,
                        "地面支援单位上前线", null);
            }
        }
        if (ground && owner != Owner.OUR) {
            return pending(owner, "地面前线单位与前线归属不一致", null);
        }
        if (hq == null || observation.hqHp() == null) {
            return pending(owner, "敌方总部位置或血量待确认", null);
        }
        if (type == UnitType.ARTILLERY) {
            return plan(Kind.ATTACK_HQ, actor, hq, TargetCategory.HQ, owner,
                    "火炮忽略守护，只攻击总部", null);
        }
        if (type == UnitType.BOMBER) {
            if (owner == Owner.ENEMY && observation.enemyFront().isEmpty()) {
                return pending(owner, "敌占前线但轰炸机目标集合未确认", null);
            }
            if (!observation.enemyFront().isEmpty()) {
                return new Plan(Kind.BOMBER_CHOICE, actor, null,
                        new BomberTargets(hq, nearest(observation.enemyFront(), actor)),
                        TargetCategory.BOMBER_CHOICE, owner, null,
                        "轰炸机在总部与敌前线之间各半选择");
            }
            return plan(Kind.ATTACK_HQ, actor, hq, TargetCategory.HQ, owner,
                    "轰炸机无敌前线时只攻击总部", null);
        }
        GuardInfo guard = observation.guard();
        if (guard.status() == GuardStatus.CLEAR) {
            return plan(Kind.ATTACK_HQ, actor, hq, TargetCategory.HQ, owner,
                    "总部无守护，优先攻击总部", null);
        }
        if (guard.status() == GuardStatus.GUARDED) {
            List<Card> legal = new ArrayList<>();
            for (Card card : guard.effectiveHqGuards()) {
                if ((card.row() == Row.ENEMY_SUPPORT || card.row() == Row.SUPPORT)
                        && !card.protectedTarget() && card.protection() != Protection.UNKNOWN) {
                    legal.add(card);
                }
            }
            if (!legal.isEmpty()) {
                return plan(Kind.ATTACK_UNIT, actor, nearest(legal, actor), TargetCategory.GUARD,
                        owner, "先解除总部守护", null);
            }
            return pending(owner, "总部有守护但相邻守护未确认或该守护也被保护", null);
        }
        return pending(owner, "总部守护状态待确认", null);
    }

    private static Card nearest(List<Card> cards, Unit actor) {
        Card base = actor.card();
        Card best = null;
        int distance = Integer.MAX_VALUE;
        for (Card card : cards) {
            int candidate = Math.abs(card.cx() - base.cx());
            if (best == null || candidate < distance) {
                best = card;
                distance = candidate;
            }
        }
        return best;
    }

    private static Plan plan(Kind kind, Unit unit, Card target, TargetCategory category,
                             Owner owner, String reason, Double roll) {
        return new Plan(kind, unit, target, category, owner, roll, reason);
    }

    private static Plan pending(Owner owner, String reason, Double roll) {
        return new Plan(Kind.PENDING, null, null, TargetCategory.NONE, owner, roll, reason);
    }

    private static void validateRoll(Double roll) {
        if (roll == null || roll < 0.0 || roll >= 1.0) {
            throw new IllegalArgumentException("bomberRoll must be in [0, 1)");
        }
    }

    private static <T> List<T> immutable(List<T> values) {
        if (values == null || values.isEmpty()) {
            return List.of();
        }
        return Collections.unmodifiableList(new ArrayList<>(values));
    }

    /** Internal pair used only while a bomber's single roll is pending. */
    private static final class BomberTargets {
        private final Card hq;
        private final Card front;

        private BomberTargets(Card hq, Card front) {
            this.hq = Objects.requireNonNull(hq);
            this.front = Objects.requireNonNull(front);
        }
    }
}
