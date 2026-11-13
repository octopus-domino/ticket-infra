import com.fasterxml.jackson.databind.ObjectMapper;
import ru.ticket.journey.OsmPlaceService;

/** Read-only provider audit; no documents, media or account data are created. */
class PlaceSourceAudit {
  public static void main(String[] args) {
    double longitude = args.length > 0 ? Double.parseDouble(args[0]) : 37.62;
    double latitude = args.length > 1 ? Double.parseDouble(args[1]) : 55.75;
    var source = new OsmPlaceService(new ObjectMapper(), "https://overpass-api.de/api/interpreter");
    long start = System.nanoTime();
    var places = source.search(longitude, latitude, "attractions", "ru");
    System.out.println("places=" + places.size() + " seconds=" + (System.nanoTime() - start) / 1_000_000_000);
    if (places.isEmpty()) throw new IllegalStateException("No live places returned");
    for (var place : places) System.out.println(place.id() + " photo=" + (place.photoReference() != null));
  }
}
