package com.kards.mobilert;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Real private-directory cleanup, including screenshots, ledgers and opening evidence. */
final class EvidenceRetentionChecks {
    private final JSONArray checks=new JSONArray();
    private static final long NOW=2000000000000L;
    private void check(String name,boolean passed) throws Exception {checks.put(new JSONObject().put("name",name).put("passed",passed));
        if(!passed)throw new IllegalStateException(name);}
    private File session(File root,String name) throws Exception {
        File session=new File(root,"battle/"+name);if(!session.mkdirs())throw new IllegalStateException("fixture_exists");
        new EvidenceRetention(root,session);return session;
    }
    private File round(File session,int index,long started,boolean closed) throws Exception {
        File round=new File(session,String.format(java.util.Locale.ROOT,"rounds/%03d",index));round.mkdirs();
        Files.write(new File(round,"retention.json").toPath(),new JSONObject().put("schema",1)
                .put("started_wall_ms",started).put("closed",closed).toString().getBytes(StandardCharsets.UTF_8));
        for(String name:new String[]{"frames/1.png","frames/1.json","inputs.jsonl","bridge-payloads.jsonl","single-action/one/before.png"}){
            File file=new File(round,name);file.getParentFile().mkdirs();Files.write(file.toPath(),new byte[]{1,2,3});
        }
        return round;
    }
    static JSONObject run(Context context) throws Exception {
        EvidenceRetentionChecks test=new EvidenceRetentionChecks();
        File root=Files.createTempDirectory(new File(context.getFilesDir(),"device-tests").toPath(),"retention-").toFile();
        File lifecycle=test.session(root,"1000000000005-eeeeeeee");
        File live=new File(lifecycle,"rounds/001");live.mkdirs();
        EvidenceRetention policy=new EvidenceRetention(root,lifecycle);
        policy.begin(live,NOW);policy.close(live);
        JSONObject closed=new JSONObject(new String(Files.readAllBytes(new File(live,"retention.json").toPath()),StandardCharsets.UTF_8));
        test.check("real_context_path_alias_can_create_and_close",closed.getBoolean("closed"));
        policy.prune(null,NOW+EvidenceRetention.MAX_AGE_MS);
        File a=test.session(root,"1000000000001-aaaaaaaa");
        File b=test.session(root,"1000000000002-bbbbbbbb");
        File[] slots=new File[102];
        for(int i=0;i<102;i++)slots[i]=test.round(i<4?a:b,i+1,NOW-(102-i)*1000,true);
        int removed=EvidenceRetention.sweep(root,b,null,NOW);
        test.check("hundred_round_safety_ceiling_across_sessions",removed==2 && !slots[0].exists() && !slots[1].exists());
        test.check("byte_budget_replaces_five_round_limit",slots[2].exists() && slots[101].exists());
        test.check("pruned_round_removes_opening_and_frame_files",!new File(slots[0],"single-action/one/before.png").exists());
        test.check("repeat_sweep_is_idempotent",EvidenceRetention.sweep(root,b,null,NOW)==0);
        File expired=test.round(b,103,NOW-EvidenceRetention.MAX_AGE_MS,true);
        File fresh=test.round(b,104,NOW-100,true);
        EvidenceRetention.sweep(root,b,null,NOW);
        test.check("seven_day_boundary_expires",!expired.exists());
        test.check("time_rule_keeps_fresh_round",fresh.exists());
        File active=test.round(b,105,NOW-EvidenceRetention.MAX_AGE_MS*2,false);
        EvidenceRetention.sweep(root,b,active,NOW);
        test.check("old_active_round_is_protected",active.exists());
        EvidenceRetention.sweep(root,b,null,NOW);
        test.check("ended_or_crashed_round_can_expire",!active.exists());
        File unmanaged=new File(root,"battle/1000000000003-cccccccc/rounds/001");unmanaged.mkdirs();
        Files.write(new File(unmanaged,"historical.png").toPath(),new byte[]{4});
        EvidenceRetention.sweep(root,b,null,NOW+EvidenceRetention.MAX_AGE_MS);
        test.check("historical_unmanaged_test_evidence_is_untouched",new File(unmanaged,"historical.png").exists());
        test.check("latest_small_status_directory_is_preserved",b.exists());
        test.check("empty_old_managed_session_is_removed",!a.exists());
        File outside=Files.createTempDirectory(context.getCacheDir().toPath(),"retention-outside-").toFile();
        File keep=new File(outside,"keep.txt");Files.write(keep.toPath(),new byte[]{5});
        File links=test.session(root,"1000000000004-dddddddd");
        File linked=test.round(links,1,NOW-EvidenceRetention.MAX_AGE_MS*2,true);
        Files.createSymbolicLink(new File(linked,"outside-link").toPath(),outside.toPath());
        EvidenceRetention.sweep(root,b,null,NOW);
        test.check("external_symlink_target_is_never_deleted",keep.exists());
        File legacy=new File(root,"battle/1000000000006-ffffffff");legacy.mkdirs();
        Files.write(new File(legacy,"retention.json").toPath(),"{\"schema\":1,\"managed\":true}".getBytes(StandardCharsets.UTF_8));
        File legacyRound=test.round(legacy,1,NOW-10*EvidenceRetention.MAX_AGE_MS,true);
        EvidenceRetention.sweep(root,b,null,NOW,0);
        test.check("old_schema_one_archive_is_preserved",legacyRound.exists());
        File budgetSession=test.session(root,"1000000000007-12345678");
        File old=test.round(budgetSession,1,NOW-1000,true);
        File newest=test.round(budgetSession,2,NOW-500,true);
        File protectedRound=test.round(budgetSession,3,NOW-100,false);
        long before=EvidenceRetention.managedBytes(root);
        EvidenceRetention.sweep(root,budgetSession,protectedRound,NOW,before-1);
        test.check("byte_pressure_evicts_oldest_round",!old.exists() && newest.exists() && protectedRound.exists());
        EvidenceRetention.sweep(root,budgetSession,protectedRound,NOW,0);
        test.check("even_zero_budget_protects_active_sources",protectedRound.exists() && !newest.exists());
        File large=new File(protectedRound,"protected-sparse.bin");
        try(java.io.RandomAccessFile sparse=new java.io.RandomAccessFile(large,"rw")){sparse.setLength(EvidenceRetention.MAX_BYTES+1);}
        boolean refused=false;
        try{new EvidenceRetention(root,budgetSession).reserve(protectedRound,NOW,1024);}
        catch(IllegalStateException expected){refused=true;}
        test.check("oversized_active_evidence_stops_without_deleting_sources",refused && large.exists());
        Files.delete(large.toPath());
        test.check("legacy_bytes_are_outside_new_policy",EvidenceRetention.managedBytes(root)<350*1024*1024L);
        WorkingFrameEvidenceChecks.run(context,test.checks);
        return new JSONObject().put("checks",test.checks).put("check_count",test.checks.length())
                .put("failure_count",0).put("device_inputs",0).put("fixture_directory",root.getAbsolutePath());
    }
}
