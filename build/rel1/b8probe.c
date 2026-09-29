/* REL1 B8 probe (docs/REL1_PACKAGING_PLAN.md 16): one triangle, one submission,
   and what the library says it sent and got back.  Run twice in a row with
   RDNMesaSeed unset: before the fix the second run's first seed repeats the
   first run's only one and the kernel refuses it (CP_WHY_SEED). */
#include <stdio.h>
#include <stdlib.h>
#include <GL/osmesa.h>
#include <GL/gl.h>
#include "OSRDNMesaTri.h"
int
main(void)
{
    void *buf = malloc(64 * 64 * 4);
    OSMesaContext c = OSMesaCreateContext(OSMESA_ARGB, NULL);
    const osrdn_tri_counts *t;

    if (buf == 0 || c == 0 || !OSMesaMakeCurrent(c, buf, GL_UNSIGNED_BYTE, 64, 64)) {
        printf("B8 setup failed\n");
        return 2;
    }
    glBegin(GL_TRIANGLES);
    glColor3f(1.0f, 0.0f, 0.0f); glVertex2f(-0.5f, -0.5f);
    glColor3f(0.0f, 1.0f, 0.0f); glVertex2f(0.5f, -0.5f);
    glColor3f(0.0f, 0.0f, 1.0f); glVertex2f(0.0f, 0.5f);
    glEnd();
    glFinish();
    t = OSRDNMesaTriCounts();
    printf("B8 seed=%lu submitted=%lu opens=%lu lastStatus=%lu lastWhy=%lu\n",
           t->seed, t->submitted, t->opens, t->lastStatus, t->lastWhy);
    return 0;
}
