import java.nio.file.Path;
import java.util.regex.Pattern;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.text.PDFTextStripper;

/** Inspect a local release-test PDF without logging poem bodies. */
class AuditPoetryPdf {
  public static void main(String[] args) throws Exception {
    try(var document=Loader.loadPDF(Path.of(args[0]).toFile())){
      String text=new PDFTextStripper().getText(document);
      long markers=Pattern.compile("(?m)^\\h*(?:5|10|15|20|25|30)(?=\\p{L})").matcher(text).results().count();
      System.out.println("pages="+document.getNumberOfPages()+" gluedMarginNumbers="+markers);
      if(markers!=0)throw new IllegalStateException("Unexpected editorial margin numbers");
    }
  }
}
