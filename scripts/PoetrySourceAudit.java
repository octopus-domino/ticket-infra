import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
import ru.ticket.journey.poetry.*;

/** Read-only live provider audit. Prints metadata and counts, never an anthology of poem texts. */
class PoetrySourceAudit {
  public static void main(String[] arguments) {
    boolean trace = Arrays.asList(arguments).contains("--trace");
    var remote = new PoetryRemoteJson(new ObjectMapper()) {
      @Override public com.fasterxml.jackson.databind.JsonNode get(String url, int limit) throws java.io.IOException {
        var response = super.get(url, limit);
        if (trace && response.has("parse")) {
          var page = response.path("parse");
          var ascii = com.fasterxml.jackson.databind.json.JsonMapper.builder().enable(com.fasterxml.jackson.core.json.JsonWriteFeature.ESCAPE_NON_ASCII).build();
          var html = org.jsoup.Jsoup.parse(page.path("text").asText());
          System.out.println("PAGE " + ascii.writeValueAsString(page.path("title")) + " verseBlocks=" + html.select(".poem").size()
              + " verseChars=" + html.select(".poem").eachText().stream().map(String::length).toList()
              + " authors=" + ascii.writeValueAsString(html.select(".ws-author a[href],a.ws-author[href],#header_author_text a[href],#header_author a[href]").eachAttr("href"))
              + " categories=" + ascii.writeValueAsString(page.path("categories")));
        }
        return response;
      }
    };
    var weather = new PoetryWeatherService(remote, "https://api.met.no/weatherapi/locationforecast/2.0/compact");
    var discovery = new PoetDiscovery(remote);
    var poems = new WikisourcePoems(remote, discovery);
    String audience = Arrays.asList(arguments).contains("--child") ? "child" : "middle";
    for (String language : arguments.length == 0 ? new String[] { "ru" } : arguments) {
      if (language.startsWith("--")) continue;
      try {
        var discovered = discovery.discover(language);
        System.out.println(language + " verifiedAuthors=" + discovered.size());
        if (trace) System.out.println(com.fasterxml.jackson.databind.json.JsonMapper.builder().enable(com.fasterxml.jackson.core.json.JsonWriteFeature.ESCAPE_NON_ASCII).build().writeValueAsString(discovered));
        if (Arrays.asList(arguments).contains("--authors-only")) continue;
        var pool = poems.poems(language, "heartfelt", audience);
        System.out.println(language + " verifiedPool=" + pool.size());
        if (Arrays.asList(arguments).contains("--pool-only")) continue;
        var forecast = weather.forecast(55.75, 37.62, "Europe/Moscow");
        var selected = PoetrySelection.select(pool, forecast.days(), language, "heartfelt", audience, "source-audit");
        System.out.println(language + " pool=" + pool.size() + " selected=" + selected.size());
        for (var poem : selected) System.out.println(poem.authorId() + " chars=" + poem.text().length() + " source=" + poem.sourceUrl());
      } catch (Exception ex) { System.out.println(language + " FAILED " + ex.getMessage() + (ex.getCause() == null ? "" : " cause=" + ex.getCause())); }
    }
  }
}
