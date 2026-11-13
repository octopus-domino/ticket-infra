import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
import ru.ticket.journey.poetry.*;

/** Explicit live read-only check. Prints counts/provenance, never full texts or MCP sessions. */
class PoemShipAudit {
  public static void main(String[] args) throws Exception {
    var mapper=new ObjectMapper();var client=new PoemShipMcpClient(mapper,"https://poemship.com/mcp");
    String language=args.length==0?"ru":args[0];
    var guide=client.call("library_guide",Map.of("language",language));
    System.out.println("language="+language+" moods="+guide.path("moods").size()+" tags="+guide.path("tags").size());
    if(Arrays.asList(args).contains("--inspect")){
      var candidates=client.call("find_poems",Map.of("language",language,"need","hope","mood","inspiring","audience","anyone","max_lines",32,"limit",10));
      System.out.println("candidateCount="+candidates.path("poems").size()+" responseFields="+candidates.properties().stream().map(Map.Entry::getKey).toList());
      for(var candidate:candidates.path("poems"))System.out.println(mapper.writeValueAsString(Map.of("title",candidate.path("title").asText(),"author",candidate.path("author").asText(),"complete",candidate.path("textIsComplete").asBoolean(),"openingType",candidate.path("firstLines").getNodeType().name(),"lines",candidate.path("lines").asInt())));
      if(Arrays.asList(args).contains("--page")&&!candidates.path("poems").isEmpty()){
        String url=candidates.path("poems").get(0).path("url").asText();
        var page=org.jsoup.Jsoup.connect(url).userAgent("CoDoc/1.0 (https://codoc.site)").timeout(8000).maxBodySize(500000).get();
        System.out.println("pageChars="+page.outerHtml().length());
        for(var element:page.select("script[type=application/ld+json]")){
          var ld=mapper.readTree(element.data());System.out.println("ldJsonFields="+ld.properties().stream().map(Map.Entry::getKey).toList());
          if(ld.has("text"))System.out.println("workType="+ld.path("@type").asText()+" authorType="+ld.path("author").getNodeType()+" authorKeys="+ld.path("author").properties().stream().map(Map.Entry::getKey).toList()+" textLines="+ld.path("text").asText().lines().filter(line->!line.isBlank()).count()+" language="+ld.path("inLanguage").asText());
        }
        for(var element:page.select("[class*=poem],[class*=verse],[itemprop=text],article,pre"))System.out.println("node="+element.tagName()+" class="+element.className()+" chars="+element.text().length());
      }
    }
    if(!Arrays.asList(args).contains("--full"))return;
    var remote=new PoetryRemoteJson(mapper);var wiki=new WikisourcePoems(remote,new PoetDiscovery(remote));
    var db=new PoetryDbProvider(remote);var tree=new PoeTreeProvider(remote,"https://versologie.cz/poetree/api");
    var provider=new PoemShipProvider(client,db,tree,wiki,new PoemShipTextResolver(mapper));
    var days=new ArrayList<PoetryWeatherService.Day>();
    for(int i=0;i<7;i++)days.add(new PoetryWeatherService.Day("2026-11-"+(13+i),"cloudy",10));
    var query=new PoetryQuery(language,"heartfelt",Arrays.asList(args).contains("--child")?"child":"middle",null,"live-audit",days);
    long start=System.nanoTime();var works=provider.find(query);
    System.out.println("completeWorks="+works.size()+" seconds="+(System.nanoTime()-start)/1_000_000_000L);
    for(var work:works)System.out.println("chars="+work.text().length()+" metadata="+mapper.writeValueAsString(work.metadata()));
  }
}
