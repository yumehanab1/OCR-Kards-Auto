package com.kards.mobilert;

import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Bounded detailed evidence. Only explicitly managed session directories are eligible. */
final class EvidenceRetention {
    static final int MAX_ROUNDS = 100;
    static final long MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000L;
    static final long MAX_BYTES = 350 * 1024 * 1024L;
    private static final String MARKER = "retention.json";
    private final File files, session;
    private long lastSweep;

    EvidenceRetention(File files, File session) throws Exception {
        this.files=files.getCanonicalFile(); this.session=session.getCanonicalFile();
        write(new File(session,MARKER),new JSONObject().put("schema",2).put("managed",true)
                .put("max_bytes",MAX_BYTES).put("screenshot_policy","lossless_working_set_jpeg_key_review"));
    }

    void begin(File round, long now) throws Exception {
        round=checkedRound(round);
        write(new File(round,MARKER),new JSONObject().put("schema",1)
                .put("started_wall_ms",now).put("closed",false));
        prune(round,now);
    }

    void close(File round) throws Exception {
        round=checkedRound(round);
        File marker=new File(round,MARKER);JSONObject value=read(marker);
        value.put("closed",true);write(marker,value);
    }

    private File checkedRound(File round) throws Exception {
        File canonical=round.getCanonicalFile();
        if(!canonical.toPath().startsWith(new File(session,"rounds").toPath()))
            throw new IllegalArgumentException("round_outside_session");
        return canonical;
    }

    void periodically(File activeRound, long now) {
        if(now-lastSweep<60000 && now>=lastSweep)return;
        prune(activeRound,now);
    }

    void prune(File activeRound, long now) {
        try { sweep(files,session,activeRound,now);lastSweep=now; }
        catch(Exception error) { android.util.Log.w("KardsRetention","Evidence cleanup deferred",error); }
    }

    void reserve(File activeRound, long now, long bytes) throws Exception {
        sweep(files,session,activeRound,now,MAX_BYTES-bytes);
        if(managedBytes(files)>MAX_BYTES-bytes)throw new IllegalStateException("managed_evidence_byte_budget");
    }

    private static final class Round {
        final File file; final long started; final boolean active;
        Round(File file,long started,boolean active){this.file=file;this.started=started;this.active=active;}
    }

    static int sweep(File files, File currentSession, File activeRound, long now) throws Exception {
        return sweep(files,currentSession,activeRound,now,MAX_BYTES);
    }

    static int sweep(File files, File currentSession, File activeRound, long now, long budget) throws Exception {
        File root=files.getCanonicalFile(),battle=new File(root,"battle");
        if(!plain(root,battle))return 0;
        List<File> sessions=new ArrayList<>();List<Round> rounds=new ArrayList<>();
        File[] children=battle.listFiles();if(children==null)return 0;
        for(File session:children){
            if(!session.getName().matches("[1-9][0-9]{0,18}-[0-9a-f]{8}") || !plain(root,session))continue;
            JSONObject marker=optional(new File(session,MARKER));
            // Schema 1 and unmarked historical evidence are preserved for explicit migration.
            if(marker==null || marker.optInt("schema")!=2 || !Boolean.TRUE.equals(marker.opt("managed")))continue;
            sessions.add(session);File directory=new File(session,"rounds");
            if(!plain(root,directory))continue;
            File[] slots=directory.listFiles();if(slots==null)continue;
            for(File slot:slots){
                if(!slot.getName().matches("[0-9]{3,10}") || !plain(root,slot))continue;
                JSONObject status=optional(new File(slot,MARKER));
                if(status==null || status.optInt("schema")!=1 || !(status.opt("started_wall_ms") instanceof Number))continue;
                long started=status.getLong("started_wall_ms");if(started<=0)continue;
                boolean active=activeRound!=null && slot.getCanonicalFile().equals(activeRound.getCanonicalFile());
                rounds.add(new Round(slot,started,active));
            }
        }
        rounds.sort(Comparator.<Round>comparingLong(x->x.started).reversed()
                .thenComparing(x->x.file.getAbsolutePath(),Comparator.reverseOrder()));
        int removed=0;
        long used=managedBytes(root);
        // Oldest closed rounds are evicted first, including their associated text evidence.
        for(int i=rounds.size()-1;i>=0;i--){
            Round round=rounds.get(i);
            // Current capture, Python postconditions and pending callbacks keep their files.
            if(!round.active && (i>=MAX_ROUNDS || now-round.started>=MAX_AGE_MS || used>budget)){
                long bytes=size(root,round.file);
                if(remove(root,round.file)){removed++;used-=bytes;}
            }
        }
        for(File session:sessions){
            File[] remaining=new File(session,"rounds").listFiles(File::isDirectory);
            if(remaining==null || remaining.length!=0)continue;
            boolean current=currentSession!=null && session.getCanonicalFile().equals(currentSession.getCanonicalFile());
            boolean active=activeRound!=null && activeRound.getCanonicalFile().toPath().startsWith(session.getCanonicalFile().toPath());
            if(active)continue;
            // Copied template banks belong to this session, not the shared embedded core.
            for(String name:new String[]{"match-entry","native-opening"}){
                File cache=new File(new File(root,name),session.getName());
                if(cache.exists())remove(root,cache);
            }
            if(!current)remove(root,session);
        }
        return removed;
    }

    static long managedBytes(File files) throws Exception {
        File root=files.getCanonicalFile(),battle=new File(root,"battle");
        if(!plain(root,battle))return 0;
        long bytes=0;File[] sessions=battle.listFiles();if(sessions==null)return 0;
        for(File session:sessions){
            if(!session.getName().matches("[1-9][0-9]{0,18}-[0-9a-f]{8}") || !plain(root,session))continue;
            JSONObject marker=optional(new File(session,MARKER));
            if(marker!=null && marker.optInt("schema")==2 && Boolean.TRUE.equals(marker.opt("managed")))
                bytes+=size(root,session);
        }
        return bytes;
    }

    private static long size(File root,File file) throws Exception {
        if(!file.getAbsoluteFile().equals(file.getCanonicalFile()) || !file.getCanonicalFile().toPath().startsWith(root.toPath()))return 0;
        if(!file.isDirectory())return file.length();
        long bytes=0;File[] children=file.listFiles();if(children==null)throw new IllegalStateException("evidence_size_unreadable");
        for(File child:children)bytes+=size(root,child);
        return bytes;
    }

    private static boolean plain(File root,File file) throws Exception {
        return file.isDirectory() && file.getAbsoluteFile().equals(file.getCanonicalFile())
                && file.getCanonicalFile().toPath().startsWith(root.toPath());
    }

    private static boolean remove(File root,File file) throws Exception {
        if(!file.getAbsoluteFile().equals(file.getCanonicalFile())
                || !file.getCanonicalFile().toPath().startsWith(root.toPath()) || file.equals(root))return false;
        if(file.isDirectory()){
            File[] children=file.listFiles();if(children==null)return false;
            for(File child:children)if(!remove(root,child))return false;
        }
        return Files.deleteIfExists(file.toPath());
    }

    private static JSONObject optional(File file){
        try{return read(file);}catch(Exception ignored){return null;}
    }
    private static JSONObject read(File file) throws Exception {
        if(!file.isFile() || file.length()>4096 || !file.getAbsoluteFile().equals(file.getCanonicalFile()))
            throw new IllegalArgumentException("invalid_retention_marker");
        return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
    }
    private static void write(File file,JSONObject value) throws Exception {
        Files.write(file.toPath(),value.toString().getBytes(StandardCharsets.UTF_8));
    }
}
