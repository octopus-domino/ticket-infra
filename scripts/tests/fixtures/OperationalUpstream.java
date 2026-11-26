import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.util.concurrent.Executors;

/** Deliberately silent HTTP and SMTP peers for the isolated operational drill. */
class OperationalUpstream {
  public static void main(String[] args) throws Exception {
    String host = args.length == 0 ? "0.0.0.0" : args[0];
    int httpPort = args.length == 0 ? 8080 : Integer.parseInt(args[1]);
    int smtpPort = args.length == 0 ? 2525 : Integer.parseInt(args[2]);
    var http = HttpServer.create(new InetSocketAddress(host, httpPort), 4);
    http.setExecutor(Executors.newFixedThreadPool(2));
    http.createContext("/brouter", exchange -> {
      System.out.println("BRouter request received");
      try {
        Thread.sleep(20_000);
      } catch (InterruptedException stopped) {
        Thread.currentThread().interrupt();
      } finally {
        exchange.close();
      }
    });
    http.start();
    try (var server = new ServerSocket()) {
      server.bind(new InetSocketAddress(host, smtpPort));
      for (;;) {
        try (var connection = server.accept()) {
          System.out.println("SMTP connection received");
          Thread.sleep(2_500);
        }
      }
    }
  }
}
