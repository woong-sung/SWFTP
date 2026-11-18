import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import oz.framework.api.RepositoryEx;
import oz.framework.repositoryex.info.*;

/** Line protocol bridge to the locally installed, official OZ 8 API. */
public class OZRepositoryBridge {
    private static final PrintStream protocol = System.out;
    private static RepositoryEx repository;
    private static final Map<String, String> categoryIds = new HashMap<String, String>();
    private static final Map<String, String> itemIds = new HashMap<String, String>();

    private static String quote(String value) {
        if (value == null) return "null";
        StringBuilder out = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c < 32) out.append(String.format("\\u%04x", (int)c));
            else out.append(c);
        }
        return out.append('"').toString();
    }

    private static void reply(String status, String value) {
        protocol.println("OZFTP\t" + status + "\t" + Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8)));
        protocol.flush();
    }

    private static String category(String path) {
        return path.endsWith("/") ? path : path + "/";
    }

    private static String parent(String path) {
        return category(path.substring(0, path.lastIndexOf('/') + 1));
    }

    private static String name(String path) {
        return path.substring(path.lastIndexOf('/') + 1);
    }

    private static String normalized(String path) {
        return path.equals("/") ? path : path.replaceAll("/+$", "");
    }

    private static String categoryId(String path) {
        String id = categoryIds.get(normalized(path));
        return id == null ? normalized(path) : id;
    }

    private static String itemId(String path) {
        String id = itemIds.get(normalized(path));
        return id == null ? normalized(path) : id;
    }

    private static String alternate(String id) {
        return id.endsWith("/") ? normalized(id) : category(id);
    }

    private static IOZCategoryInfo[] folders(String id) throws Exception {
        IOZCategoryInfo[] result;
        try {
            result = repository.getCategoryListInCategory(id, false).getCategoryInfos();
        } catch (Exception error) {
            if (id.equals("/")) throw error;
            try { return repository.getCategoryListInCategory(alternate(id), false).getCategoryInfos(); }
            catch (Exception ignored) { throw error; }
        }
        if ((result == null || result.length == 0) && !id.equals("/")) {
            try { return repository.getCategoryListInCategory(alternate(id), false).getCategoryInfos(); }
            catch (Exception ignored) { /* A valid empty directory stays empty. */ }
        }
        return result;
    }

    private static IOZItemInfo[] items(String id) throws Exception {
        IOZItemInfo[] result;
        try {
            result = repository.getItemListInCategory(id).getItemInfos();
        } catch (Exception error) {
            if (id.equals("/")) throw error;
            try { return repository.getItemListInCategory(alternate(id)).getItemInfos(); }
            catch (Exception ignored) { throw error; }
        }
        if ((result == null || result.length == 0) && !id.equals("/")) {
            try { return repository.getItemListInCategory(alternate(id)).getItemInfos(); }
            catch (Exception ignored) { /* Preserve the successful original result. */ }
        }
        return result;
    }

    private static void check(boolean success, int[] codes, String[] messages) throws IOException {
        if (!success || codes[0] != 0) throw new IOException("OZ " + codes[0] + ": " + messages[0]);
    }

    private static String listing(String path) throws Exception {
        path = normalized(path);
        String requestedId = categoryId(path);
        StringBuilder json = new StringBuilder("[");
        IOZCategoryInfo[] folders = folders(requestedId);
        if (folders != null) for (IOZCategoryInfo folder : folders) {
            String id = folder.getCategoryID();
            if (normalized(id).equals(normalized(requestedId))) continue;
            String childName = folder.getCategoryName();
            if (childName == null || childName.isEmpty()) childName = name(id.replaceAll("/+$", ""));
            childName = name(normalized(childName));
            categoryIds.put(category(path) + childName, id);
            json.append("{\"id\":").append(quote(id)).append(",\"name\":").append(quote(childName)).append(",\"dir\":true,\"size\":0,\"mtime\":")
                .append(folder.getUpdateTime()).append(",\"owner\":").append(quote(folder.getCreateUserName())).append("},");
        }
        IOZItemInfo[] items = items(requestedId);
        if (items != null) for (IOZItemInfo item : items) {
            String itemName = name(normalized(item.getItemName()));
            itemIds.put(category(path) + itemName, item.getItemID());
            json.append("{\"id\":").append(quote(item.getItemID())).append(",\"name\":").append(quote(itemName)).append(",\"dir\":false,\"size\":")
                .append(item.getSize()).append(",\"mtime\":").append(item.getUpdateTime())
                .append(",\"owner\":").append(quote(item.getCreateUserName())).append("},");
        }
        if (json.charAt(json.length() - 1) == ',') json.setLength(json.length() - 1);
        return json.append(']').toString();
    }

    private static void progress(long count, long total) {
        protocol.println("OZFTP\tPROGRESS\t" + count + "\t" + total);
        protocol.flush();
    }

    private static String execute(String[] args) throws Exception {
        String command = args[0];
        int[] codes = new int[1];
        String[] messages = new String[1];
        if (command.equals("connect")) {
            repository = new RepositoryEx(args[1], args[2], args[3], Boolean.parseBoolean(args[4]));
            categoryIds.clear();
            itemIds.clear();
            categoryIds.put("/", "/");
            return listing("/");
        }
        if (command.equals("list")) return listing(args[1]);
        if (command.equals("get")) {
            String path = itemId(args[1]);
            long total = repository.getItemInfo(path).getSize();
            InputStream[] streams = repository.getItemsUnCondition(new String[]{path}, new boolean[]{false},
                new boolean[]{false}, new String[]{repository.getCategoryIdOfItem(path)}, codes, messages);
            check(streams != null && streams.length == 1 && streams[0] != null, codes, messages);
            try (InputStream input = streams[0]; OutputStream output = Files.newOutputStream(Paths.get(args[2]))) {
                byte[] buffer = new byte[65536];
                long count = 0;
                int length;
                while ((length = input.read(buffer)) != -1) {
                    output.write(buffer, 0, length);
                    count += length;
                    progress(count, total);
                }
            }
            return "null";
        }
        if (command.equals("put")) {
            final long total = Files.size(Paths.get(args[1]));
            String path = itemId(args[2]);
            try (InputStream input = new FilterInputStream(Files.newInputStream(Paths.get(args[1]))) {
                long count = 0;
                public int read() throws IOException {
                    int value = in.read();
                    if (value != -1) progress(++count, total);
                    return value;
                }
                public int read(byte[] b, int off, int len) throws IOException {
                    int length = in.read(b, off, len);
                    if (length > 0) { count += length; progress(count, total); }
                    return length;
                }
            }) {
                if (repository.hasTheItem(path)) {
                    boolean[] result = repository.checkInItem(new String[]{path}, new boolean[]{false},
                        new InputStream[]{input}, "FTP Client upload", new boolean[]{false}, codes, messages);
                    check(result != null && result.length == 1 && result[0], codes, messages);
                } else {
                    String[] result = repository.createItem(new String[]{name(path)}, new String[]{""},
                        new String[]{categoryId(parent(args[2]))}, new boolean[]{false}, new InputStream[]{input},
                        "FTP Client upload", codes, messages);
                    check(result != null && result.length == 1 && result[0] != null, codes, messages);
                    itemIds.put(normalized(args[2]), result[0]);
                }
            }
            return "null";
        }
        if (command.equals("mkdir")) {
            String[] result = repository.createCategory(new String[]{name(args[1])}, new String[]{categoryId(parent(args[1]))},
                "FTP Client", codes, messages);
            check(result != null && result.length == 1 && result[0] != null, codes, messages);
            categoryIds.put(normalized(args[1]), result[0]);
            return "null";
        }
        if (command.equals("remove")) {
            boolean[] result = repository.deleteItem(new String[]{itemId(args[1])}, new boolean[]{false}, "FTP Client", codes, messages);
            check(result != null && result.length == 1 && result[0], codes, messages);
            return "null";
        }
        if (command.equals("rmdir")) {
            if (args[1].equals("/") || !listing(args[1]).equals("[]")) throw new IOException("Directory is not empty or is root.");
            boolean[] result = repository.deleteCategory(new String[]{categoryId(args[1])}, new boolean[]{false}, "FTP Client", codes, messages);
            check(result != null && result.length == 1 && result[0], codes, messages);
            return "null";
        }
        if (command.equals("quit")) {
            if (repository != null) repository.logoutToServer();
            return "null";
        }
        throw new IOException("Unsupported OZ operation: " + command);
    }

    public static void main(String[] argv) throws Exception {
        // SDK logs never share the response channel.
        System.setOut(System.err);
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = reader.readLine()) != null) {
            String[] parts = line.split("\t", -1);
            String[] args = new String[parts.length];
            for (int i = 0; i < parts.length; i++) args[i] = new String(Base64.getDecoder().decode(parts[i]), StandardCharsets.UTF_8);
            try { reply("OK", execute(args)); }
            catch (Exception error) { reply("ERROR", error.getClass().getSimpleName() + ": " + error.getMessage()); }
            if (args[0].equals("quit")) break;
        }
    }
}
