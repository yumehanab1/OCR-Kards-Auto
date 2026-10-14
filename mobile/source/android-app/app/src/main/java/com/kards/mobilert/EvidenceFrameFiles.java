package com.kards.mobilert;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.LinkOption;

/** Two immutable evidence paths for one original PNG, without duplicate storage. */
final class EvidenceFrameFiles {
    private EvidenceFrameFiles() { }
    static String mirror(File source, File target) throws IOException {
        return mirror(source,target,true);
    }
    static String mirror(File source, File target, boolean tryLink) throws IOException {
        if (Files.exists(target.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new FileAlreadyExistsException(target.getAbsolutePath());
        if (tryLink) {
            try {
                Files.createLink(target.toPath(),source.toPath());
                return "shared_original_inode";
            } catch (IOException | UnsupportedOperationException unavailable) {
                // Different mounts or unsupported filesystems retain the old
                // exact-byte copy. Existing destinations still fail closed.
            }
        }
        if (Files.exists(target.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new FileAlreadyExistsException(target.getAbsolutePath());
        Files.copy(source.toPath(),target.toPath());
        return "byte_copy";
    }
}
